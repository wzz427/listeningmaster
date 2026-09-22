"""用大模型生成教学内容：每句的中文翻译、每个词在本集语境里的中文意思、按话题分的段。

决策 D3：只在备课阶段离线跑一次，结果写进课程文件；播放器不调接口。
决策 D12：第一版就要中文释义，所以这一步排在播放器前面。
决策 D22：正文按话题切成两分钟左右一段，一段一段精听；每段一个中文小标题。
规则 R13（specs/SPEC-001-player.md）：生成的内容要 owner 审过才给孩子用。

原始返回存在 lessons/<课>/teach_raw.json，方便复查模型到底说了什么。

重跑时默认复用上一版 lesson.json 里已有的翻译、词条和分段，只给新出现的句子和词调模型。
这样改了句子起止时间（refine_bounds.py）之后重建课程文件，不会把 owner 审过的中文换掉。
要全部重新生成就加 --fresh；只重切分段、中文不动就加 --resplit。
"""

import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import call  # noqa: E402
import tts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODEL = "deepseek-flash"   # 选型见 lessons/260821/model_compare.md
SENTENCES_PER_CALL = 25
WORDS_PER_CALL = 80
SECTION_SECONDS = 120      # 每段尽量不超过这么长（owner 2026-09-21：每段两分钟以内）
OUTSIDE = "片头片尾"

WHO = ("你在为一个刚通过剑桥 PET（B1）、听力偏弱的中国初中生准备英语听力材料的中文辅助内容。"
       "用词要简单、口语化，别用书面腔，别解释得太长。")


def translate(sentences: list[dict], context: str, model: str = MODEL) -> dict[int, str]:
    out: dict[int, str] = {}
    for i in range(0, len(sentences), SENTENCES_PER_CALL):
        chunk = sentences[i:i + SENTENCES_PER_CALL]
        payload = [{"id": s["id"], "speaker": s["speaker"], "text": s["text"]} for s in chunk]
        data, _ = call(
            model,
            WHO + "把每句英文翻成自然的中文口语，一句对一句，不要逐词硬译，不要加解释。"
                  "遇到这一集正在教的英文词（例如 decaf、cut down on），保留英文再补一句中文意思。"
                  '只输出 JSON：{"items":[{"id":数字,"zh":"中文"}]}',
            f"这一集的完整内容（只作背景，不用翻译）：\n{context}\n\n"
            f"要翻译的句子：\n{json.dumps(payload, ensure_ascii=False)}",
        )
        for item in data["items"]:
            out[int(item["id"])] = item["zh"].strip()
        print(f"  翻译进度 {min(i + SENTENCES_PER_CALL, len(sentences))}/{len(sentences)}")
    return out


def gloss(words: list[str], context: str, model: str = MODEL) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(words), WORDS_PER_CALL):
        chunk = words[i:i + WORDS_PER_CALL]
        data, _ = call(
            model,
            WHO + "给每个词写它在这一集里的意思：lemma 是原形，zh 是中文意思（不超过 12 个字，"
                  "有多个意思时只给这一集里用到的那个）。"
                  "hard 表示：这个词本身，或者它在这一集里的这个意思，B1（剑桥 PET）水平的学生"
                  "可能不认识。常见词用在特殊意思上也算生词，例如 take your coffee black 里的 "
                  "take、black。"
                  '原样保留 w 字段。只输出 JSON：'
                  '{"items":[{"w":"...","lemma":"...","zh":"...","hard":true}]}',
            f"这一集的完整内容：\n{context}\n\n"
            f"要解释的词：\n{json.dumps(chunk, ensure_ascii=False)}",
        )
        for item in data["items"]:
            out[item["w"]] = {
                "lemma": item.get("lemma", item["w"]),
                "zh": item["zh"].strip(),
                "hard": bool(item.get("hard", False)),
            }
        print(f"  词条进度 {min(i + WORDS_PER_CALL, len(words))}/{len(words)}")
    return out


def split_sections(body: list[dict], model: str = MODEL) -> list[dict]:
    """按话题把正文切成几段，返回 [{"first": 这段第一句的 id, "title": 中文小标题}]。

    只让模型给每段的第一句，段和段天然首尾相接，不会漏句、不会重叠。
    """
    payload = [{"id": s["id"], "t": round(s["start"]), "speaker": s["speaker"], "text": s["text"]}
               for s in body]
    total = body[-1]["end"] - body[0]["start"]
    # 只说上限时，模型会切得很碎（2026-09-21 第一次切成 6 段、每段 40 到 70 秒），所以把段数告诉它
    count = math.ceil(total / SECTION_SECONDS)
    data, _ = call(
        model,
        WHO + f"这一集要给孩子一段一段地精听。正文一共约 {total:.0f} 秒，按话题切成 {count} 段左右，"
              f"段数宁少勿多：只要每段不超过约 {SECTION_SECONDS} 秒，就别再往细里切。"
              "只在换话题的地方切，别把一问一答切开；"
              "节目最后如果有复习词汇、道别，单独成一段。t 是这句开始的秒数，用来估每段多长。"
              "每段起一个中文小标题，不超过 14 个字，说这段在聊什么，但不说出答案"
              "（写「不喝咖啡会怎样」，不写「不喝咖啡会犯困」）。"
              '只输出 JSON：{"sections":[{"first":这段第一句的 id,"title":"中文小标题"}]}',
        json.dumps(payload, ensure_ascii=False),
    )
    ids = [s["id"] for s in body]
    titles = {int(x["first"]): x["title"].strip() for x in data["sections"] if int(x["first"]) in ids}
    if not titles:
        raise ValueError("模型给的分段一个都对不上正文的句子，重跑一次")
    if ids[0] not in titles:  # 第一段必须从正文第一句开始
        titles[ids[0]] = titles.pop(min(titles))
    return [{"first": k, "title": titles[k]} for k in sorted(titles)]


def with_last(cuts: list[dict], body: list[dict]) -> list[dict]:
    """补上每段最后一句的 id，并打印每段多长，给 owner 过目。"""
    ids = [s["id"] for s in body]
    by_id = {s["id"]: s for s in body}
    out = []
    for n, cut in enumerate(cuts):
        last = ids[ids.index(cuts[n + 1]["first"]) - 1] if n + 1 < len(cuts) else ids[-1]
        out.append({"first": cut["first"], "last": last, "title": cut["title"]})
        seconds = by_id[last]["end"] - by_id[cut["first"]]["start"]
        count = ids.index(last) - ids.index(cut["first"]) + 1
        warn = "  ← 偏长" if seconds > SECTION_SECONDS + 30 else ""
        print(f"  第 {n + 1} 段  {seconds // 60:.0f} 分 {seconds % 60:02.0f} 秒  {count} 句  {cut['title']}{warn}")
    return out


def normalize(token: str) -> str:
    return re.sub(r"[^a-z0-9']", "", token.lower().replace("\u2019", "'"))


def load_previous(lesson_dir: Path) -> tuple[dict[str, str], dict[str, dict], dict[str, str]]:
    """上一版课程文件里已有的内容：{英文句子: 中文}、词条、{每段第一句的英文: 小标题}。"""
    path = lesson_dir / "lesson.json"
    if not path.exists():
        return {}, {}, {}
    old = json.loads(path.read_text(encoding="utf-8"))
    text_of = {s["id"]: s["text"] for s in old["sentences"]}
    return ({s["text"]: s["zh"] for s in old["sentences"] if s.get("zh")},
            old.get("glossary", {}),
            {text_of[x["first"]]: x["title"] for x in old.get("sections", [])})


def reuse_sections(old: dict[str, str], body: list[dict]) -> list[dict] | None:
    """上一版的每个分段起点都还在，就按英文原句找回来；缺一个就整体重切。"""
    if not old:
        return None
    first_of = {s["text"]: s["id"] for s in body}
    if any(text not in first_of for text in old):
        return None
    return sorted(({"first": first_of[text], "title": title} for text, title in old.items()),
                  key=lambda x: x["first"])


def build(lesson: str, fresh: bool = False, resplit: bool = False) -> None:
    lesson_dir = ROOT / "lessons" / lesson
    timeline = json.loads((lesson_dir / "timeline.json").read_text(encoding="utf-8"))
    sentences = timeline["sentences"]
    context = " ".join(s["text"] for s in sentences)

    forms = sorted({normalize(w["text"]) for s in sentences for w in s["words"]} - {""})
    known_zh, glossary, old_sections = ({}, {}, {}) if fresh else load_previous(lesson_dir)
    todo_sentences = [s for s in sentences if s["text"] not in known_zh]
    todo_words = [w for w in forms if w not in glossary]
    print(f"{len(sentences)} 句，{len(forms)} 个不同的词；"
          f"要新生成的：{len(todo_sentences)} 句、{len(todo_words)} 个词")

    new_zh = translate(todo_sentences, context) if todo_sentences else {}
    if todo_words:
        glossary.update(gloss(todo_words, context))
    zh_map = {s["id"]: new_zh.get(s["id"]) or known_zh.get(s["text"], "") for s in sentences}

    body = [s for s in sentences if s["speaker"] != OUTSIDE]
    cuts = None if resplit else reuse_sections(old_sections, body)
    print("分段：沿用上一版" if cuts else "分段：让模型按话题切")
    sections = with_last(cuts or split_sections(body), body)

    (lesson_dir / "teach_raw.json").write_text(
        json.dumps({"zh": zh_map, "glossary": glossary, "sections": sections},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    for s in sentences:
        s["zh"] = zh_map.get(s["id"], "")
        for w in s["words"]:
            w["key"] = normalize(w["text"])

    lesson_data = {
        "lesson": lesson,
        "title": "Coffee",
        "source": "BBC Learning English · Real Easy English",
        "audio": "audio.m4a",
        "bodyStart": body[0]["start"] if body else 0,
        "sections": sections,
        "sentences": sentences,
        "glossary": glossary,
        # 单词朗读：备课时生成好的文件，孩子那边不连任何外部服务（决策 D26）
        "tts": {"voice": tts.VOICES[tts.VOICE], "files": tts.build(lesson_dir, sorted(glossary))},
    }
    (lesson_dir / "lesson.json").write_text(
        json.dumps(lesson_data, ensure_ascii=False, indent=2), encoding="utf-8")
    hard = sum(1 for g in glossary.values() if g["hard"])
    print(f"写出 lesson.json：{len(sentences)} 句带中文，{len(glossary)} 个词条，其中标为生词的 {hard} 个，"
          f"正文分 {len(sections)} 段")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    build(args[0] if args else "260821", fresh="--fresh" in sys.argv, resplit="--resplit" in sys.argv)
