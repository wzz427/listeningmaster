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
from bisect import bisect_right
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcript import Turn, read_turns  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTSIDE = "片头片尾"      # 讲稿里没有的部分
NOISE_RUN = 2             # 连续不超过这么多个词的「说话人倒退」当噪声
MEGA = 20                 # 归一化后超过这么长字符的「词」只可能是识别粘词拼出来的巨词


@dataclass
class Word:
    text: str                      # 带前导空格的原样文本，拼起来就是整句
    start: float                   # 秒
    end: float
    turn: int | None = None        # 对应讲稿第几个话轮
    script_word: str | None = None # 讲稿里对应的那个词
    script_idx: int | None = None  # 那个词在讲稿词序列里的位置（拆粘词时当游标）


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


def _regroup_by_script(toks: list[dict], script: list[tuple[int, str]], b: str, starts: list[int]) -> list[Word] | None:
    """识别偶尔整段不给词间空格（2026-10-28，250123 快餐那集：词片全不带前导空格、
    时间间隙也是零），按前导空格拼词只能拼成一个几十字符的巨词，整句对不上讲稿。
    这里拿讲稿做字符级对齐，把词片按讲稿的词界重新分组：拼写用讲稿的，时间取所在词片的首尾。
    字符对不上八成的（讲稿里没有的片头片尾、预告）返回 None，不硬切。"""
    a_parts = [normalize(tok["text"]) for tok in toks]
    a = "".join(a_parts)
    blocks = SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    if sum(m.size for m in blocks) < len(a) * 0.8:
        return None
    owner = [-1] * len(a)
    for m in blocks:
        for k in range(m.size):
            owner[m.a + k] = bisect_right(starts, m.b + k) - 1
    # 每个词片跟着它最后一个字符所属的讲稿词；归属不明的词片（纯标点）跟着前一组
    groups: list[tuple[int, list[dict]]] = []
    pos = 0
    for tok, part in zip(toks, a_parts):
        if not part:
            no = groups[-1][0] if groups else -1
        else:
            no = owner[min(pos + len(part) - 1, len(a) - 1)]
        pos += len(part)
        if groups and (no == groups[-1][0] or no < 0):
            groups[-1][1].append(tok)
        else:
            groups.append((no, [tok]))
    out: list[Word] = []
    for no, members in groups:
        spelling = script[no][1] if no >= 0 else "".join(m["text"] + m.get("punctuation", "") for m in members)
        out.append(Word((" " if out else "") + spelling,
                        members[0]["begin_time"] / 1000, members[-1]["end_time"] / 1000))
    return out if len(out) > 1 else None


def merge_tokens(asr: dict, turns: list[Turn]) -> tuple[list[list[Word]], int]:
    """把识别结果里的子词碎片拼成整词。以空格开头的碎片表示新词的开始。

    例：'Georg' + 'ie' → 'Georgie'；'I' + "'" + 'm' → "I'm"。
    拼出巨词（≥MEGA 字符）说明识别这段没给空格，改按讲稿重切（见 _regroup_by_script）。
    返回（每句的词列表，重切了几句）。"""
    script = [(i, w) for i, t in enumerate(turns) for w in t.text.split()]
    starts: list[int] = []
    parts: list[str] = []
    for _, w in script:
        starts.append(len("".join(parts)))
        parts.append(normalize(w))
    b = "".join(parts)
    out: list[list[Word]] = []
    respaced = 0
    for sent in asr["transcripts"][0]["sentences"]:
        words: list[Word] = []
        toks = sent["words"]
        for tok in toks:
            piece = tok["text"] + tok.get("punctuation", "")
            if words and not tok["text"].startswith(" "):
                words[-1].text += piece
                words[-1].end = tok["end_time"] / 1000
            else:
                words.append(Word(piece, tok["begin_time"] / 1000, tok["end_time"] / 1000))
        if words and any(len(normalize(w.text)) >= MEGA for w in words) and toks:
            regrouped = _regroup_by_script(toks, script, b, starts)
            if regrouped and len(regrouped) > len(words):
                words = regrouped
                respaced += 1
        if words:
            out.append(words)
    return out, respaced


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
            words[block.a + k].script_idx = block.b + k
            matched += 1
    return matched, len(b)


def split_glued_pairs(sentences_tokens: list[list[Word]], turns: list[Turn]) -> tuple[int, int]:
    """识别偶尔把相邻两三个词粘成一个（2026-09 第一集见过 It means → Itmeans；
    2026-10-28 第二次出现：250123 里 cando、dreamswhich、shopburger——欠账表说过出现第二次就修）。
    没对上讲稿的词，若讲稿游标后面紧挨的两到四个词连起来正好等于它，就按讲稿拆开：
    拼写用讲稿的，时间按字符数分（后面 refine_bounds、ear_bounds 还会按声音修边界）。
    返回（拆了几个词，多对上了几个词）。"""
    script = [(i, w) for i, t in enumerate(turns) for w in t.text.split()]
    nxt = 0   # 讲稿游标：只会往前走
    fixed = gained = 0
    for words in sentences_tokens:
        i = 0
        while i < len(words):
            w = words[i]
            if w.script_idx is not None:
                nxt = max(nxt, w.script_idx + 1)
                i += 1
                continue
            nw = normalize(w.text)
            span = 0
            if len(nw) >= 4:
                for k in (2, 3, 4):
                    if nxt + k <= len(script):
                        joined = "".join(normalize(script[j][1]) for j in range(nxt, nxt + k))
                        if joined and joined == nw:
                            span = k
                            break
            if not span:
                i += 1
                continue
            total = len(nw)
            t0, t1 = w.start, w.end
            lead = " " if w.text.startswith(" ") else ""   # 第一个词沿用原来的前导空格
            new_words: list[Word] = []
            used = 0
            for j in range(span):
                turn, spelling = script[nxt + j]
                n = len(normalize(spelling))
                s = t0 + (t1 - t0) * used / total
                used += n
                e = t1 if j == span - 1 else t0 + (t1 - t0) * used / total
                piece = Word((lead if j == 0 else " ") + spelling, s, e, turn, spelling, nxt + j)
                new_words.append(piece)
            words[i:i + 1] = new_words
            gained += span
            fixed += 1
            nxt += span
            i += span
    return fixed, gained


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
        raise SystemExit("这份材料没有讲稿，暂时备不了：在资料库里这条材料上点「＋讲稿」，"
                         "把 BBC 页面的讲稿传上来（TXT、PDF、MD 都行）再备课")
    turns = read_turns(script)

    sentences_tokens, respaced = merge_tokens(asr, turns)
    all_words = [w for s in sentences_tokens for w in s]
    matched, script_total = match_script(all_words, turns)
    pair_fixed, pair_gained = split_glued_pairs(sentences_tokens, turns)
    matched += pair_gained
    all_words = [w for s in sentences_tokens for w in s]   # 拆粘词改了句内的词列表，重新摊平
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
        f"- 识别粘词按讲稿重切：{respaced} 句（识别没给词间空格的巨词）" if respaced else "",
        f"- 粘成一块的相邻词拆开：{pair_fixed} 处，多对上 {pair_gained} 个词" if pair_fixed else "",
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
    print(f"对上的词：{matched}/{script_total}（{matched / script_total:.0%}），修正噪声 {smoothed} 个"
          + (f"，粘词重切 {respaced} 句" if respaced else ""))
    print(f"已写出 {(lesson_dir / 'timeline.json').relative_to(ROOT)} 和 align_report.md")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    build(sys.argv[1] if len(sys.argv) > 1 else "260821")
