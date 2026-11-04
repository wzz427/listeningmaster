"""无讲稿材料的对齐切句（SPEC-013）：材料夹里没有 transcript 时，句子、文字、说话人全凭识别结果。

有讲稿照走 align.py（一条不动）；run.py 按材料夹里有没有讲稿挑路，这份只管没讲稿的那条。四步：
拼词（R3，按词片前导空格）→ 巨词加空格（R4，大模型＋字母校验，退词频，再不行原样）→
标点并半句（R5，只看逗号/小写，不看说话人——编号还没归并成真人，同人异编号看不出「同人」）→
编号归并成人＋起名（R6，大模型五条铁律；拿不准 Role A/B 是 owner 2026-11-04 定的）。
片头预告不剔（R7 忠实还原）：大模型若把头尾的短编号判成 promo，就标「片头片尾」——
句子照留在时间轴里、照翻中文，只是不进正文分段，和带讲稿课的片头片尾同一个待遇。

两处大模型调用（巨词、起名）的回答缓存在 lessons/<课>/llm_cache.json：同样的问法只问一次，
重放不联网不花钱（金样考卷 A6 吃的就是它，tests/fixtures/free/ 里存着一份）。
"""

import hashlib
import json
import math
import re
import sys
from pathlib import Path

from wordfreq import word_frequency

sys.path.insert(0, str(Path(__file__).resolve().parent))          # 同包的 align
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # pipeline/ 根上的 llm
from align import MEGA, OUTSIDE, Sentence, Word, normalize  # noqa: E402
from llm import call  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
MODEL = "deepseek-flash"   # 和备课其余大模型调用同款（SPEC-000 R5）

MEGA_SYSTEM = (
    "你拿到的是语音识别输出的英文，识别时忘了在词和词之间留空格，整句挤成了一长串字母。"
    "你的任务：把空格加回去，还原成正常的英语句子。"
    "铁律：只许插入空格（和必要的撇号还原），不许改任何一个字母、不许增删字母；"
    "人名、品牌名（Beth、KFC、McDonald's 这类）要保持原样。"
    '输出 JSON：{"cuts": ["切好的第 1 句", "切好的第 2 句", ...]}，条数和输入一致。'
)

NAME_SYSTEM = (
    "你拿到一集英语听力材料（对话播客、有声故事、单词朗读都有可能）的逐句转写，"
    "每句开头的数字是机器按音色分出的说话人编号。"
    "编号有两个毛病：可能把同一个人拆成两三个编号，也可能把片头音乐、节目预告分出额外编号。\n"
    "你的任务：判断这一集真正有几位说话人，把每个编号归到人。五条铁律：\n"
    "1. 只统计真在对话里开口说话的人。**被谈到的人不是说话人**：名字出现在别人话里、"
    "被第三人称讲述、被引用过一句半句的，都不算。\n"
    "2. 对话播客通常只有两三位说话人，有声故事、单词朗读常常只有一位。"
    "拿不准某编号是不是新的人时，优先把它并进已有的某人（按它说话的内容和接话的位置判断更像谁）。\n"
    "3. **拆分比新面孔常见得多**：出现在中间的编号，几乎一定是某位说话者被拆出来的，"
    "按内容并回对应的说话者。promo（片头片尾音乐、广告、节目预告）只出现在整集的开头或结尾，"
    "中间不会插播 promo——中间的编号别标 promo。\n"
    "4. 能从内容确认名字的用真名（典型线索：两人互相打招呼 Hi Phil / Hi Georgie）；"
    "但凡有一点点不够确认，就用 Role A、Role B 标记，不要硬猜名字。\n"
    "5. 每个编号底下标了它出现的时间段和句数，中段短编号（几句话、嵌在两人对话之间）"
    "基本是拆分；头尾的短编号才可能是音乐或预告。\n"
    '输出 JSON：{"speakers": "一句话说明几位说话人", '
    '"labels": {"0": "名字或Role A或promo", "1": "...", ...}}，每个编号都要有。'
)


def ask(system: str, user: str, cache: dict) -> dict:
    """带缓存的大模型调用：同样的问法只问一次。缓存由 build 落盘（llm_cache.json）。"""
    key = hashlib.sha1((system + "\x00" + user).encode("utf8")).hexdigest()
    if key not in cache:
        cache[key], _ = call(MODEL, system, user)
    return cache[key]


def merge_words(asr: dict) -> list[Sentence]:
    """R3 拼词：照识别词片的前导空格拼整词，规则与带讲稿路相同——少了「按讲稿重切」那一半，
    拼出巨词的留给 R4 加空格。每句的 speaker 暂存识别给的编号（spk0、spk1…）。"""
    out: list[Sentence] = []
    for sent in asr["transcripts"][0]["sentences"]:
        words: list[Word] = []
        for tok in sent.get("words") or []:
            piece = tok["text"] + tok.get("punctuation", "")
            if words and not tok["text"].startswith(" "):
                words[-1].text += piece
                words[-1].end = tok["end_time"] / 1000
            else:
                words.append(Word(piece, tok["begin_time"] / 1000, tok["end_time"] / 1000))
        if words:
            out.append(Sentence(words[0].start, words[-1].end,
                                f"spk{sent.get('speaker_id') or 0}", words))
    return out


def _expand(blob: Word, spellings: list[str]) -> list[Word]:
    """巨词拆开的几个词按字母数分时间（拼写用切出来的；边界还有精修和机器耳朵两道修）。"""
    weights = [max(len(normalize(p)), 1) for p in spellings]
    total, span = sum(weights), blob.end - blob.start
    lead = " " if blob.text.startswith(" ") else ""
    out, used = [], 0
    for j, (piece, weight) in enumerate(zip(spellings, weights)):
        start = blob.start + span * used / total
        used += weight
        end = blob.end if j == len(spellings) - 1 else blob.start + span * used / total
        out.append(Word((lead if j == 0 else " ") + piece, start, end))
    return out


def _tidy_pieces(spellings: list[str], blob: Word) -> list[str] | None:
    """大模型切出来的词片：字母校验在调用处；这里收尾——纯标点的碎片并给前一个词、
    句末标点丢了就从原样补回。返回 None 表示这版切法用不了（交词频兜底）。"""
    if not spellings:
        return None
    tidied: list[str] = []
    for piece in spellings:
        if tidied and not normalize(piece):
            tidied[-1] += piece
        else:
            tidied.append(piece)
    if len(tidied) < 2:
        return None
    tail = re.search(r"[^\w']*$", blob.text).group()
    if tail and not tidied[-1].endswith(tail):
        tidied[-1] += tail
    return tidied


def _dp_cut(text: str) -> list[str] | None:
    """R4 词频兜底：一长串字母按常用词切开——动态规划找「每段都是真词、词频加起来最高」的切法。
    词频表里没有的段按字母数罚：按段罚会让整段不切只挨一次罚、反而占便宜（探针一版的教训，
    docs/research/2026-11-03-no-transcript-ablation.md「补法验证」）。切不出两段以上返回 None。"""
    s = normalize(text)
    if len(s) < 2:
        return None
    best: dict[int, tuple[float, list[str]]] = {0: (0.0, [])}
    for i in range(1, len(s) + 1):
        for j in range(max(0, i - 24), i):
            if j not in best:
                continue
            piece = s[j:i]
            freq = word_frequency(piece, "en", wordlist="best")
            score = best[j][0] + (math.log10(freq) if freq > 0 else -1.2 * len(piece)) - 0.05
            if i not in best or score > best[i][0]:
                best[i] = (score, best[j][1] + [piece])
    pieces = best.get(len(s), (0.0, None))[1]
    return pieces if pieces and len(pieces) > 1 else None


def split_megas(sentences: list[Sentence], cache: dict) -> dict:
    """R4 巨词（归一化后 ≥MEGA 字符）：先交大模型加空格（一课最多一次调用），校验切完的
    字母序列和原来一字不差；不过关退词频切法，再不行原样保留。"""
    jobs = [(s, i) for s in sentences for i, w in enumerate(s.words) if len(normalize(w.text)) >= MEGA]
    stat = {"mega_total": len(jobs), "mega_llm": 0, "mega_dp": 0, "mega_kept": 0}
    if not jobs:
        return stat
    result = ask(MEGA_SYSTEM, json.dumps({"blobs": [s.words[i].text.strip() for s, i in jobs]},
                                         ensure_ascii=False), cache)
    cuts = result.get("cuts") or []
    plan: list[tuple[Sentence, int, list[str] | None]] = []
    for k, (sent, idx) in enumerate(jobs):
        blob = sent.words[idx]
        spellings = None
        cut = cuts[k] if k < len(cuts) else None
        if isinstance(cut, str) and normalize(cut) == normalize(blob.text):
            spellings = _tidy_pieces(cut.split(), blob)   # 字母一字不差才敢用
        if spellings:
            stat["mega_llm"] += 1
        else:
            dp = _dp_cut(blob.text)
            if dp:
                dp[0] = dp[0][0].upper() + dp[0][1:]      # 词频给的是小写：首词补个大写
                tail = re.search(r"[^\w']*$", blob.text).group()
                if tail and not dp[-1].endswith(tail):
                    dp[-1] += tail
                spellings = dp
                stat["mega_dp"] += 1
            else:
                stat["mega_kept"] += 1
        plan.append((sent, idx, spellings))
    # 倒着替换，一句里有多个巨词时后面的下标不失效
    for sent, idx, spellings in reversed(plan):
        if spellings:
            sent.words[idx:idx + 1] = _expand(sent.words[idx], spellings)
    return stat


MAX_SECONDS = 15   # 并出来的整句不超过这么长——再长就不是一句人话，重听没法练


def merge_halves(sentences: list[Sentence]) -> int:
    """R5 并半句：前句以逗号结尾、或（前句以句末标点收尾且）后句以小写字母开头就并
    （并时去掉识别点在半句处的句号）。不看说话人：编号还没归并成真人，同一个人的两个编号
    看不出「同人」（四课实测拆碎句 7/8/8/10 → 2/6/3/4，出处同上）。
    两条护栏（overpop 科普课踩出来的，2026-11-04）：①小写判据只在前句以 . ! ? 收尾时作数——
    要修的病是「识别把半句点成了整句」；整段没标句读的转写句句小写，见小写就并会把
    6 分半并成 12 句、最长一句 4 分半；②并完不超过 MAX_SECONDS 秒。"""
    merged: list[Sentence] = []
    count = 0
    for s in sentences:
        prev = merged[-1] if merged else None
        joins = (
            prev is not None
            and s.end - prev.start <= MAX_SECONDS
            and (prev.text.endswith(",") or (s.text[:1].islower() and prev.text[-1:] in (".", "!", "?")))
        )
        if joins:
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


def name_speakers(sentences: list[Sentence], cache: dict) -> tuple[dict[str, str], str]:
    """R6 ②：编号归并成人＋起名交大模型（五条铁律，2026-11-04 三轮探针调到四课 85/94/81/97%，
    docs/research/2026-11-04-speaker-diarization-services.md）。返回（spk 编号→显示名，模型的一句话说明）。
    promo 一律归「片头片尾」（R7：句子照留，只是不进正文）；大小写不同的同名并成一个；
    没答上来的编号补 Role X，不跟已有的重。"""
    dur = sentences[-1].end if sentences else 0.0
    by: dict[int, list[Sentence]] = {}
    for s in sentences:
        by.setdefault(int(s.speaker[3:]), []).append(s)
    stats = [f"{k}：{len(v)} 句，出现在 {v[0].start:.0f}–{v[-1].end:.0f} 秒（全集 {dur:.0f} 秒）"
             for k, v in sorted(by.items())]
    lines = [f"{int(s.speaker[3:])} {s.text}" for s in sentences]
    result = ask(NAME_SYSTEM,
                 "各编号概况：\n" + "\n".join(stats)
                 + "\n\n以下是这集的逐句转写：\n" + "\n".join(lines), cache)
    raw = result.get("labels") or {}
    labels: dict[str, str] = {}
    seen: dict[str, str] = {}
    for k in sorted(by):
        name = str(raw.get(str(k), raw.get(f"spk{k}", ""))).strip()
        low = name.lower()
        if low in ("promo", "音乐", "片头片尾"):
            name = OUTSIDE
        elif low in seen:
            name = seen[low]
        elif name:
            seen[low] = name
        labels[f"spk{k}"] = name
    used = {v.lower() for v in labels.values() if v}
    spare = [c for c in "ABCDEFGH" if f"role {c.lower()}" not in used]
    for k in sorted(by):
        if not labels[f"spk{k}"]:
            labels[f"spk{k}"] = f"Role {spare.pop(0)}" if spare else "Role Z"
    return labels, str(result.get("speakers") or "").strip()


def build(lesson: str, root: Path = ROOT) -> dict:
    """无讲稿路的对齐步（run.py 挑路进来，位置同 align.build）：出 timeline.json＋align_report.md，
    返回质量统计（run.py 的质量报告用）。"""
    lesson_dir = root / "lessons" / lesson
    asr = json.loads((lesson_dir / "asr_raw.json").read_text(encoding="utf-8"))
    cache_path = lesson_dir / "llm_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf8")) if cache_path.exists() else {}
    had = len(cache)

    sentences = merge_words(asr)
    mega = split_megas(sentences, cache)
    # 起名在并句之前：吃识别的原句（选型探针同口径），并句的就地改动进不了提示词——
    # 两条规则解耦，调并句不用重问起名（考卷的缓存键也稳）
    labels, note = name_speakers(sentences, cache)
    merged = merge_halves(sentences)
    for s in sentences:
        s.speaker = labels.get(s.speaker, s.speaker)
    if len(cache) > had:   # 这一课新问过大模型才写盘，重放不动它
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf8")

    timeline = {
        "lesson": lesson,
        "audio": next((root / "materials" / lesson).glob("*.mp3")).name,
        "sentences": [
            {
                "id": i, "speaker": s.speaker, "start": round(s.start, 2), "end": round(s.end, 2),
                "text": s.text,
                "words": [{"text": w.text.strip(), "start": round(w.start, 2), "end": round(w.end, 2)}
                          for w in s.words],
            }
            for i, s in enumerate(sentences)
        ],
    }
    (lesson_dir / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf8")

    people = sorted({s.speaker for s in sentences} - {""})
    outside = sum(1 for s in sentences if s.speaker == OUTSIDE)
    report = [
        f"# 无讲稿对齐报告 · {lesson}", "",
        f"- 识别 {len(sentences) + merged} 句 → 拼词、并半句后 {len(sentences)} 句（并了 {merged} 处）",
        f"- 巨词恢复：识别挤成一团的 {mega['mega_total']} 处——大模型加空格 {mega['mega_llm']} 处、"
        f"词频兜底 {mega['mega_dp']} 处、原样保留 {mega['mega_kept']} 处",
        f"- 说话人：识别分出 {len(labels)} 个编号，归并成 {len(people) - (1 if OUTSIDE in people else 0)} 位"
        + (f"（另有 {outside} 句判为片头/预告，句子照留）" if outside else ""),
        f"- 模型的话：{note or '—'}",
        "- 没有讲稿可对，不出对上率；文字凭识别原样（消融实测拼错 0 个，见调研报告）",
        "- 编号归并表：" + "、".join(f"{k}→{v}" for k, v in sorted(labels.items())),
        "",
        "## 时间轴（秒）",
        "",
        "| # | 起 | 止 | 说话人 | 内容 |",
        "|---|---|---|---|---|",
    ]
    for s in timeline["sentences"]:
        report.append(f"| {s['id']} | {s['start']:.2f} | {s['end']:.2f} | {s['speaker']} | {s['text']} |")
    (lesson_dir / "align_report.md").write_text("\n".join(report) + "\n", encoding="utf8")

    print(f"无讲稿路：{len(sentences)} 句，说话人 {len(people) - (1 if OUTSIDE in people else 0)} 位"
          + (f"（{outside} 句片头/预告照留）" if outside else "")
          + f"，并半句 {merged} 处，巨词 {mega['mega_total']} 处（大模型 {mega['mega_llm']}／词频 {mega['mega_dp']}／保留 {mega['mega_kept']}）")
    print(f"已写出 {(lesson_dir / 'timeline.json').relative_to(root)} 和 align_report.md")
    return {"path": "free", "sentences": len(sentences), "merged": merged, **mega,
            "speaker_ids": len(labels), "speakers": len(people) - (1 if OUTSIDE in people else 0),
            "labels": labels, "note": note, "outside": outside}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    build(sys.argv[1] if len(sys.argv) > 1 else "hans")
