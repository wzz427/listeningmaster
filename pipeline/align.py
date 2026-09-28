"""把识别结果和讲稿对起来：句子以识别结果为准，说话人和拼写来自讲稿。

决策 D1：屏幕上显示录音里实际说的话，讲稿只用来校正拼写、分句和说话人。
决策 D4：说话人用讲稿标注，不用识别模型的说话人分离（实测 103 句里有 96 句被判成同一人）。

做法：两边都切成词、做同样的归一化，用 difflib 求最长匹配。
匹配上的词继承讲稿话轮的说话人，并采用讲稿的拼写和大小写；
中间没匹配上的词跟前一个词走；开头结尾没匹配上的整段是片头片尾，不算正文。
一句话里跨了两个说话人就按词的时间切开。
"""

import json
import re
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcript import Turn, read_turns  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTSIDE = "片头片尾"      # 讲稿里没有的部分
NOISE_RUN = 2             # 连续不超过这么多个词的「说话人倒退」当噪声


@dataclass
class Word:
    text: str                      # 带前导空格的原样文本，拼起来就是整句
    start: float                   # 秒
    end: float
    turn: int | None = None        # 对应讲稿第几个话轮
    script_word: str | None = None # 讲稿里对应的那个词


@dataclass
class Sentence:
    start: float
    end: float
    speaker: str
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(w.text for w in self.words).strip()


def normalize(token: str) -> str:
    """只留字母数字和撇号，用来判断两个词算不算同一个词。"""
    return re.sub(r"[^a-z0-9']", "", token.lower().replace("\u2019", "'"))


def merge_tokens(asr: dict) -> list[list[Word]]:
    """把识别结果里的子词碎片拼成整词。以空格开头的碎片表示新词的开始。

    例：'Georg' + 'ie' → 'Georgie'；'I' + "'" + 'm' → "I'm"。
    """
    out: list[list[Word]] = []
    for sent in asr["transcripts"][0]["sentences"]:
        words: list[Word] = []
        for tok in sent["words"]:
            piece = tok["text"] + tok.get("punctuation", "")
            if words and not tok["text"].startswith(" "):
                words[-1].text += piece
                words[-1].end = tok["end_time"] / 1000
            else:
                words.append(Word(piece, tok["begin_time"] / 1000, tok["end_time"] / 1000))
        if words:
            out.append(words)
    return out


def match_script(words: list[Word], turns: list[Turn]) -> tuple[int, int]:
    """逐词匹配讲稿，返回（对上的词数，讲稿词数）。"""
    script = [(i, w) for i, t in enumerate(turns) for w in t.text.split()]
    a = [normalize(w.text) for w in words]
    b = [normalize(w) for _, w in script]
    matched = 0
    for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            words[block.a + k].turn = script[block.b + k][0]
            words[block.a + k].script_word = script[block.b + k][1]
            matched += 1
    return matched, len(b)


def smooth_turns(words: list[Word]) -> int:
    """话轮号应该随时间只增不减。个别词匹配到了更早的话轮，按噪声处理。

    例：Neil 那句开头的 so 被匹配到 Georgie 更早说过的 so，会平白切出一个半秒的碎句。
    """
    runs: list[tuple[int, list[int]]] = []
    for i, w in enumerate(words):
        if w.turn is None:
            continue
        if runs and runs[-1][0] == w.turn:
            runs[-1][1].append(i)
        else:
            runs.append((w.turn, [i]))
    fixed, current = 0, -1
    for turn, members in runs:
        if turn < current and len(members) <= NOISE_RUN:
            for i in members:
                words[i].turn = current
                fixed += 1
        else:
            current = max(current, turn)
    return fixed


def fill_gaps(words: list[Word]) -> None:
    """中间没匹配上的词跟前一个词走；开头结尾整段没匹配上的留空，那是片头片尾。"""
    later = [False] * len(words)
    seen = False
    for i in range(len(words) - 1, -1, -1):
        later[i] = seen
        seen = seen or words[i].turn is not None
    last = None
    for i, w in enumerate(words):
        if w.turn is not None:
            last = w.turn
        elif last is not None and later[i]:
            w.turn = last


def correct_spelling(word: Word) -> str:
    """匹配上的词采用讲稿的拼写和大小写，保留识别结果里的前导空格和标点。"""
    if not word.script_word:
        return word.text
    lead = " " if word.text.startswith(" ") else ""
    tail = re.search(r"[^\w']*$", word.text).group()
    return lead + word.script_word.strip(".,!?;:\u2014- ") + tail


def split_by_speaker(sentences: list[list[Word]], turns: list[Turn]) -> list[Sentence]:
    """按说话人切句：一句话里换了人就从换人的那个词切开。"""
    def name(word: Word) -> str:
        return turns[word.turn].speaker if word.turn is not None else OUTSIDE

    out: list[Sentence] = []
    for words in sentences:
        current: list[Word] = []
        for w in words:
            if current and name(w) != name(current[0]):
                out.append(Sentence(current[0].start, current[-1].end, name(current[0]), current))
                current = []
            current.append(w)
        if current:
            out.append(Sentence(current[0].start, current[-1].end, name(current[0]), current))
    return out


def merge_fragments(sentences: list[Sentence]) -> int:
    """识别有时在逗号处把一句切成两半（例如单独一个 So,）。同一个说话人的碎片并回下一句。

    判据：同说话人，并且上一句以逗号结尾，或者下一句以小写字母开头。
    重听的单位应该是一个完整意思，半句话没法练。
    """
    merged: list[Sentence] = []
    count = 0
    for s in sentences:
        prev = merged[-1] if merged else None
        joins = (
            prev is not None
            and prev.speaker == s.speaker
            and (prev.text.endswith(",") or s.text[:1].islower())
        )
        if joins:
            # 识别在半句处点了句号（例如 in the morning. and one usually...），并句时去掉
            if s.text[:1].islower() and prev.words[-1].text.rstrip().endswith("."):
                prev.words[-1].text = prev.words[-1].text.rstrip().rstrip(".")
            if not s.words[0].text.startswith(" "):
                s.words[0].text = " " + s.words[0].text
            prev.words.extend(s.words)
            prev.end = s.end
            count += 1
        else:
            merged.append(s)
    sentences[:] = merged
    return count


def build(lesson: str) -> None:
    lesson_dir = ROOT / "lessons" / lesson
    asr = json.loads((lesson_dir / "asr_raw.json").read_text(encoding="utf-8"))
    material_dir = ROOT / "materials" / lesson
    script = next(material_dir.glob("*transcript.pdf"), None) or next(material_dir.glob("transcript.txt"), None)
    if script is None:  # 对外版 v1 要讲稿（SPEC-009 R5）；没讲稿的路是 SPEC-002 R8 的欠账
        raise SystemExit("这份材料没有讲稿，暂时备不了：上传时把 BBC 页面的讲稿粘进来（纯文本就行）")
    turns = read_turns(script)

    sentences_tokens = merge_tokens(asr)
    all_words = [w for s in sentences_tokens for w in s]
    matched, script_total = match_script(all_words, turns)
    smoothed = smooth_turns(all_words)
    fill_gaps(all_words)
    for w in all_words:
        w.text = correct_spelling(w)
    sentences = split_by_speaker(sentences_tokens, turns)
    joined = merge_fragments(sentences)

    timeline = {
        "lesson": lesson,
        "audio": next(material_dir.glob("*.mp3")).name,
        "sentences": [
            {
                "id": i,
                "speaker": s.speaker,
                "start": round(s.start, 2),
                "end": round(s.end, 2),
                "text": s.text,
                "words": [
                    {"text": w.text.strip(), "start": round(w.start, 2), "end": round(w.end, 2)}
                    for w in s.words
                ],
            }
            for i, s in enumerate(sentences)
        ],
    }
    (lesson_dir / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")

    body = [s for s in sentences if s.speaker != OUTSIDE]
    report = [
        f"# 对齐报告 · {lesson}",
        "",
        f"- 识别出的词：{len(all_words)}　讲稿的词：{script_total}　"
        f"两边对上的词：{matched}（占讲稿 {matched / script_total:.0%}）",
        f"- 识别出但讲稿里没有的词：{len(all_words) - matched} 个（片头片尾、口头语、识别错的）",
        f"- 讲稿里有但没对上的词：{script_total - matched} 个（讲稿不是逐字稿）",
        f"- 说话人倒退按噪声修正的词：{smoothed} 个，并回上一句的碎片：{joined} 处",
        f"- 识别给出 {len(sentences_tokens)} 句，按说话人切开后 {len(sentences)} 句，"
        f"其中正文 {len(body)} 句、片头片尾 {len(sentences) - len(body)} 句",
        "",
        "## 时间轴（秒）",
        "",
        "| # | 起 | 止 | 说话人 | 内容 |",
        "|---|---|---|---|---|",
    ]
    for s in timeline["sentences"]:
        report.append(f"| {s['id']} | {s['start']:.2f} | {s['end']:.2f} | {s['speaker']} | {s['text']} |")
    (lesson_dir / "align_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"句子：{len(sentences_tokens)} → {len(sentences)}（正文 {len(body)} 句）")
    print(f"对上的词：{matched}/{script_total}（{matched / script_total:.0%}），修正噪声 {smoothed} 个")
    print(f"已写出 {(lesson_dir / 'timeline.json').relative_to(ROOT)} 和 align_report.md")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    build(sys.argv[1] if len(sys.argv) > 1 else "260821")
