"""用千问生成教学内容：每句的中文翻译、每个词在本集语境里的中文意思。

决策 D3：只在备课阶段离线跑一次，结果写进课程文件；播放器不调接口。
决策 D12：第一版就要中文释义，所以这一步排在播放器前面。
规则 R13（specs/SPEC-001-player.md）：生成的内容要 owner 审过才给孩子用。

原始返回存在 lessons/<课>/teach_raw.json，方便复查模型到底说了什么。
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import call  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODEL = "deepseek-flash"   # 选型见 lessons/260821/model_compare.md
SENTENCES_PER_CALL = 25
WORDS_PER_CALL = 80

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


def normalize(token: str) -> str:
    return re.sub(r"[^a-z0-9']", "", token.lower().replace("\u2019", "'"))


def build(lesson: str) -> None:
    lesson_dir = ROOT / "lessons" / lesson
    timeline = json.loads((lesson_dir / "timeline.json").read_text(encoding="utf-8"))
    sentences = timeline["sentences"]
    context = " ".join(s["text"] for s in sentences)

    forms = sorted({normalize(w["text"]) for s in sentences for w in s["words"]} - {""})
    print(f"{len(sentences)} 句，{len(forms)} 个不同的词")

    zh_map = translate(sentences, context)
    glossary = gloss(forms, context)

    (lesson_dir / "teach_raw.json").write_text(
        json.dumps({"zh": zh_map, "glossary": glossary}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    for s in sentences:
        s["zh"] = zh_map.get(s["id"], "")
        for w in s["words"]:
            w["key"] = normalize(w["text"])

    body = [s for s in sentences if s["speaker"] != "片头片尾"]
    lesson_data = {
        "lesson": lesson,
        "title": "Coffee",
        "source": "BBC Learning English · Real Easy English",
        "audio": "audio.m4a",
        "bodyStart": body[0]["start"] if body else 0,
        "sentences": sentences,
        "glossary": glossary,
    }
    (lesson_dir / "lesson.json").write_text(
        json.dumps(lesson_data, ensure_ascii=False, indent=2), encoding="utf-8")
    hard = sum(1 for g in glossary.values() if g["hard"])
    print(f"写出 lesson.json：{len(sentences)} 句带中文，{len(glossary)} 个词条，其中标为生词的 {hard} 个")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    build(sys.argv[1] if len(sys.argv) > 1 else "260821")
