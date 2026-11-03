"""无讲稿材料的消融实验（2026-11-03 owner 拍板；报告 docs/research/2026-11-03-no-transcript-ablation.md）。

问的问题（SPEC-003「还没解决的」、docs/debts.md 那行）：一份材料没有讲稿，现在的流水线
直接跑会差多少？差在三处看得见的地方——

  ① 说话人：识别自带的分离（asr_raw.json 的 speaker_id）代替讲稿话轮，能对上几句；
  ② 屏幕上的字：没有讲稿校正拼写、拆粘词，识别原样的词里有多少错的（Itmeans、巨词）；
  ③ 片头片尾／预告：没有「对不上讲稿＝不算正文」这条判据，片头和结尾预告全漏进正文。

做法：识别本来就不吃讲稿（SPEC-003 决策依据），四课的 asr_raw.json 都在仓库里，
金样答案就是仓库里带讲稿跑出来的 timeline.json——两边按时间重叠配对、逐词比对，
全程离线、不联网、不花钱（机器耳朵那两步只管边界准不准，和讲稿无关，不用跑）。

跑法：<pywork python> pipeline/ablation_no_transcript.py    出 ablation/<课>.md＋ablation/summary.md
（ablation/ 在 .gitignore 里：随脚本能重新生成，长久住处是调研报告。）
"""

import json
import sys
from itertools import permutations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "slicing"))
from align import MEGA, OUTSIDE, normalize  # noqa: E402  和生产同一条归一化、同一个巨词阈值

ROOT = Path(__file__).resolve().parent.parent
LESSONS = ["260821", "250123", "250918", "261009"]
OUT = ROOT / "ablation"


def raw_sentences(asr: dict) -> list[dict]:
    """识别原样拼词（align.merge_tokens 去掉讲稿那半边）：前导空格开头的词片算新词，
    巨词、粘词照识别原样留着——这正是没有讲稿时屏幕上拿到的词。"""
    out = []
    for sent in asr["transcripts"][0]["sentences"]:
        words = []
        for tok in sent["words"]:
            piece = tok["text"] + tok.get("punctuation", "")
            if words and not tok["text"].startswith(" "):
                words[-1]["text"] += piece
                words[-1]["end"] = tok["end_time"] / 1000
            else:
                words.append({"text": piece, "start": tok["begin_time"] / 1000,
                              "end": tok["end_time"] / 1000})
        if words:
            out.append({"start": sent["begin_time"] / 1000, "end": sent["end_time"] / 1000,
                        "speaker_id": sent.get("speaker_id"), "words": words})
    return out


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def best_pair(raw: list[dict], gold: list[dict]):
    """每个金样句子配时间重叠最大的识别句（配说话人用），返回 {金样下标: 识别下标}。"""
    pair = {}
    for gi, g in enumerate(gold):
        best, best_ov = -1, 0.0
        for ri, r in enumerate(raw):
            ov = overlap(g["start"], g["end"], r["start"], r["end"])
            if ov > best_ov:
                best, best_ov = ri, ov
        if best >= 0:
            pair[gi] = best
    return pair


def speaker_score(raw: list[dict], gold_body: list[dict], names: list[str]) -> dict:
    """识别自带的说话人分离对答案。映射取对识别最有利的那一种（两个标号对两个名字，
    穷举置换取最高分），然后按「金样句子配到的那句识别」数对错——分数高说明分离真能用，
    分数低说明塌了，不是映射没找对。"""
    ids = sorted({r["speaker_id"] for r in raw})
    pair = best_pair(raw, gold_body)
    best = None
    for perm in permutations(names, len(ids)):
        m = dict(zip(ids, perm))
        ok = sum(1 for gi, ri in pair.items() if m[raw[ri]["speaker_id"]] == gold_body[gi]["speaker"])
        if best is None or ok > best["ok"]:
            best = {"mapping": m, "ok": ok}
    wrong = [gi for gi, ri in pair.items() if best["mapping"][raw[ri]["speaker_id"]] != gold_body[gi]["speaker"]]
    # 塌没塌：识别把多少句判给了同一个人（两个主持人对话，单边超过八成就是塌）
    counts = {}
    for r in raw:
        counts[r["speaker_id"]] = counts.get(r["speaker_id"], 0) + 1
    return {"mapping": best["mapping"], "ok": best["ok"], "total": len(gold_body),
            "wrong": wrong, "counts": counts,
            "collapsed": max(counts.values()) / len(raw) >= 0.8 if counts else True}


def text_score(raw: list[dict], gold_body: list[dict]) -> dict:
    """金样正文时间里的识别原样词，逐词找时间重叠的金样词比拼写。
    注意金样的字本来就是「识别原话＋讲稿校正」（SPEC-003 R4），所以这里量的是讲稿对屏幕文字
    的净贡献，分四类：对上（含大小写差——识别常把句首和小写 i 写成小写，上屏看得见）；
    巨词（≥MEGA 字符，识别整段没给空格）；粘词（等于几个金样词连起来）；剩下的拼写错。"""
    gold_words = [(g["speaker"], w) for g in gold_body for w in g["_words"]]
    matched = casediff = mega = glued = other = 0
    examples = {"巨词": [], "粘词": [], "拼写": [], "大小写": []}
    for r in raw:
        for w in r["words"]:
            mid = (w["start"] + w["end"]) / 2
            if not any(g["start"] <= mid < g["end"] for g in gold_body):
                continue                      # 片头片尾时间里的词不算（那笔账在漏进正文里记）
            hits = [gw for spk, gw in gold_words if overlap(w["start"], w["end"], gw["start"], gw["end"]) > 0]
            nw = normalize(w["text"])
            if hits and nw == normalize(hits[0]["text"]):
                if w["text"].strip() != hits[0]["text"].strip():
                    casediff += 1             # 同一个词，识别的大小写和讲稿的不一样
                    if len(examples["大小写"]) < 6:
                        examples["大小写"].append(f"{w['text'].strip()}→{hits[0]['text'].strip()}")
                else:
                    matched += 1
                continue
            if len(nw) >= MEGA:
                mega += 1
                examples["巨词"].append(w["text"].strip()[:50])
            elif len(hits) >= 2 and nw == "".join(normalize(h["text"]) for h in hits):
                glued += 1
                examples["粘词"].append(w["text"].strip())
            else:
                other += 1
                if nw:
                    examples["拼写"].append(w["text"].strip()[:30])
    total = matched + casediff + mega + glued + other
    return {"total": total, "matched": matched, "casediff": casediff, "mega": mega, "glued": glued,
            "other": other, "examples": {k: v[:6] for k, v in examples.items()}}


def leak_score(raw: list[dict], gold: list[dict]) -> dict:
    """金样判成片头片尾的句子（片头＋结尾预告），没有讲稿的版本一句都剔不掉、全当正文教。"""
    outside = [g for g in gold if g["speaker"] == OUTSIDE]
    leaked = sum(sum(1 for r in raw if overlap(g["start"], g["end"], r["start"], r["end"]) > 0.3 * (g["end"] - g["start"]))
                 for g in outside)
    return {"outside_sentences": len(outside),
            "outside_seconds": round(sum(g["end"] - g["start"] for g in outside), 1),
            "raw_sentences_inside": leaked,
            "spans": [(round(g["start"], 1), round(g["end"], 1)) for g in outside]}


def unit_score(raw: list[dict], gold_body: list[dict]) -> dict:
    """重听单位（整句能不能一刀回到句首）。金样句被拆散的判据：有两截以上识别句
    各占它 0.3 秒以上（各占一段才叫拆散；金样边界被机器耳朵挪过的零点几秒晃动不算数）。
    反过来一句识别句里混了两个金样说话人的算「两人说成一句」。"""
    split, split_ex = 0, []
    for g in gold_body:
        pieces = [r for r in raw if overlap(g["start"], g["end"], r["start"], r["end"]) >= 0.3]
        if len(pieces) >= 2:
            split += 1
            if len(split_ex) < 8:
                text = " ".join(w["text"].strip() for w in g["_words"])[:60]
                split_ex.append(f"{text} ← {len(pieces)} 截")
    mixed = []
    for r in raw:
        spk = set()
        for g in gold_body:
            if overlap(r["start"], r["end"], g["start"], g["end"]) >= 0.3:
                spk.add(g["speaker"])
        if len(spk) > 1:
            mixed.append(spk)
    return {"raw_count": len(raw), "gold_count": len(gold_body),
            "shattered": split, "shattered_examples": split_ex, "mixed": len(mixed)}


def run(lesson: str) -> dict:
    asr = json.loads((ROOT / "lessons" / lesson / "asr_raw.json").read_text(encoding="utf-8"))
    gold_raw = json.loads((ROOT / "lessons" / lesson / "timeline.json").read_text(encoding="utf-8"))
    gold = [{"start": s["start"], "end": s["end"], "speaker": s["speaker"],
             "_words": s.get("words", [])} for s in gold_raw["sentences"]]
    gold_body = [g for g in gold if g["speaker"] != OUTSIDE]
    names = sorted({g["speaker"] for g in gold_body})
    raw = raw_sentences(asr)

    spk = speaker_score(raw, gold_body, names)
    txt = text_score(raw, gold_body)
    leak = leak_score(raw, gold)
    unit = unit_score(raw, gold_body)
    return {"lesson": lesson, "spk": spk, "txt": txt, "leak": leak, "unit": unit,
            "raw": raw, "gold_body": gold_body, "names": names}


def write_lesson_report(res: dict) -> None:
    les, spk, txt, leak, unit = (res["lesson"], res["spk"], res["txt"], res["leak"], res["unit"])
    lines = [
        f"# 无讲稿消融 · {les}", "",
        "识别原样（不喂讲稿）对比仓库金样 timeline.json，全程离线。", "",
        "## ① 说话人（识别自带的分离）", "",
        f"- 识别句数 {unit['raw_count']}，标号分布 {spk['counts']}"
        f"——{'塌了（八成以上判成同一人）' if spk['collapsed'] else '没塌'}",
        f"- 映射取最有利的（{spk['mapping']}）之后：正文 {spk['total']} 句里对 {spk['ok']} 句"
        f"（{spk['ok'] / spk['total']:.0%}）",
        f"- 错句金样下标（前 20）：{spk['wrong'][:20]}", "",
        "## ② 屏幕上的字（拼写只能照识别）", "",
        f"- 正文时间里识别原样词 {txt['total']} 个：一字不差 {txt['matched']}"
        f"（{txt['matched'] / max(txt['total'], 1):.0%}）、大小写差 {txt['casediff']}、巨词 {txt['mega']}、"
        f"粘词 {txt['glued']}、拼写错 {txt['other']}",
        f"- 大小写例：{txt['examples']['大小写']}",
        f"- 巨词例：{txt['examples']['巨词']}",
        f"- 粘词例：{txt['examples']['粘词']}",
        f"- 拼写例：{txt['examples']['拼写']}", "",
        "## ③ 片头片尾／预告漏进正文", "",
        f"- 金样剔了 {leak['outside_sentences']} 句共 {leak['outside_seconds']} 秒"
        f"（位置 {leak['spans']}）；没有讲稿一句也剔不掉，落进正文的识别句 {leak['raw_sentences_inside']} 句", "",
        "## ④ 重听单位", "",
        f"- 识别 {unit['raw_count']} 句 vs 金样正文 {unit['gold_count']} 句；金样句被碎句拆散的 "
        f"{unit['shattered']} 句；一句识别里混了两个说话人的 {unit['mixed']} 句",
        f"- 拆散的例：{unit['shattered_examples']}", "",
    ]
    (OUT / f"{les}.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    results = [run(les) for les in LESSONS]
    for res in results:
        write_lesson_report(res)
    lines = [
        "# 无讲稿消融 · 汇总", "",
        "| 课 | 说话人对（最有利映射） | 词一字不差 | 大小写差 | 巨词/粘词/拼写错 | 片头预告漏进 | 碎句拆散/混话轮 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        spk, txt, leak, unit = r["spk"], r["txt"], r["leak"], r["unit"]
        lines.append(
            f"| {r['lesson']} | {spk['ok']}/{spk['total']}（{spk['ok'] / spk['total']:.0%}）"
            f"{'，塌' if spk['collapsed'] else ''} | {txt['matched']}/{txt['total']}"
            f"（{txt['matched'] / max(txt['total'], 1):.0%}） | {txt['casediff']} | "
            f"{txt['mega']}/{txt['glued']}/{txt['other']} | "
            f"{leak['outside_sentences']} 句 {leak['outside_seconds']} 秒 | "
            f"{unit['shattered']} / {unit['mixed']} |")
    (OUT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n细账在 {OUT.relative_to(ROOT)}\\<课>.md")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
