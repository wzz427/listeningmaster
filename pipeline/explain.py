"""孩子点词时现查：讲这个词（词组）在这句里的意思，展开看常见意思、搭配、例句；词组和词典里没有的词现读。

为什么点了才查（owner 2026-09-22，决策 D29）：一份材料几千个词，孩子真正点的也就十来个，
不该在备课时把每个词都讲一遍；备课要快，几分钟以内。
由 pipeline/serve.py 的 /api/explain、/api/speak 调；密钥只在本地服务里，网页里没有（以后上服务器，放网关）。
查过的存在 lessons/<课>/explain_cache.json，同一处再点、别的孩子点同一处都直接返回。

讲得好不好靠提示词（owner：不挑错，不给孩子标「电脑生成」，写对提示词就行）。
改了提示词，删掉 explain_cache.json 就会按新的重新查；抽查用：<pywork python> pipeline/explain.py sample [课] [个数]
"""

import json
import random
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import call  # noqa: E402
import tts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODEL = "deepseek-flash"   # 不开思考模式（llm.call 里关的），一次不到一秒
LOCK = threading.Lock()

PROMPT = """你在帮一个刚通过剑桥 PET（B1）、听力偏弱的中国初中生听英语。他听的时候点了句子里的一个词，想知道它在这句里是什么意思。

按下面的要求讲：
1. 先看点的这个词是不是和旁边的词组成固定说法：短语动词（cut down on、give up）、固定词组（at the moment、a bit、first thing in the morning）、打招呼之类的套话（How are you）。是的话讲整个词组，words 写词组里每个词的序号；不是就只讲这个词，words 只写它自己的序号。
2. here：一两句中文，不超过 45 个字。先说它在这句里的意思，再结合前后文点明这句在说什么。要贴着这句话讲，别泛泛地背词典。
3. more：给想多了解的孩子看。
   - senses：这个词（词组）最常用的意思，1 到 3 个，每个不超过 12 个字，按常用程度排。只写中学生常会遇到的真实意思，拿不准的不写，宁少勿错。
     每个意思都要真能放进一句常见的英文里用；别把近义词的意思安到它头上（「讲某种语言」是 speak，不是 say），
     也别把搭配、用量当成一个意思（「一勺糖」不是 sugar 的意思）。只有一个常见意思就只写一个。
   - used：这句用的是 senses 里的第几个（从 1 数），这句的意思一定要在 senses 里。
   - collocations：这个意思最常见的搭配 2 到 3 个，英文加中文，英文要是英语母语的人真会这么说的。
   - example：一个新例句，别照抄原句，用 B1 学生认识的词，不超过 12 个词，英文加中文。
   冠词、代词、介词、连词、be 动词这类虚词，还有人名、地名、节目名：more 写 null，here 一句话说清它在这句里的作用或者指的是谁。
4. 中文要口语、简单，少用语法术语，孩子是初中生。

例子：句子 You take your coffee black. 点了 black（序号 4），输出
{"words":[4],"text":"black","here":"这里指咖啡不加牛奶，就是黑咖啡。这句在说你喝咖啡不加奶。","more":{"senses":["黑色的","（咖啡）不加奶的"],"used":2,"collocations":[{"en":"black coffee","zh":"黑咖啡"},{"en":"drink it black","zh":"不加奶喝"}],"example":{"en":"I always have my tea black.","zh":"我喝茶从来不加奶。"}}}

只输出 JSON：{"words":[序号],"text":"...","here":"...","more":{...} 或 null}"""


def _cache_path(lesson: str) -> Path:
    return ROOT / "lessons" / lesson / "explain_cache.json"


def _read_cache(lesson: str) -> dict:
    path = _cache_path(lesson)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_cache(lesson: str, cache: dict) -> None:
    _cache_path(lesson).write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def _load(lesson: str) -> dict:
    return json.loads((ROOT / "lessons" / lesson / "lesson.json").read_text(encoding="utf-8"))


def ask(sentences: list[dict], n: int, i: int) -> dict:
    """调模型讲第 n 句的第 i 个词，返回整理好的讲解。"""
    s = sentences[n]
    payload = {
        "before": sentences[n - 1]["text"] if n else "",
        "sentence": s["text"],
        "after": sentences[n + 1]["text"] if n + 1 < len(sentences) else "",
        "words": [{"i": k, "w": w["text"].strip(".,?!;:\"")} for k, w in enumerate(s["words"])],
        "clicked": i,
    }
    for attempt in range(3):  # 偶尔返回的 JSON 不完整，再要一次
        try:
            data, _ = call(MODEL, PROMPT, json.dumps(payload, ensure_ascii=False))
            break
        except ValueError:
            if attempt == 2:
                raise
    words = sorted({int(k) for k in data.get("words") or [] if 0 <= int(k) < len(s["words"])} | {i})
    if max(words) - min(words) > 5:  # 拼得太远的不当词组
        words = [i]
    more = data.get("more") or None
    if more and not (isinstance(more.get("used"), int) and 1 <= more["used"] <= len(more.get("senses") or [])):
        more["used"] = None
    text = data.get("text", "").strip() if len(words) > 1 else s["words"][i]["text"].strip(".,?!;:\"")
    return {"words": words, "text": text, "here": (data.get("here") or "").strip(), "more": more}


def explain(lesson: str, sid: int, i: int) -> dict:
    """第 sid 句第 i 个词的讲解；查过的直接返回。"""
    key = f"{sid}:{i}"
    with LOCK:
        cache = _read_cache(lesson)
    if key in cache:
        return cache[key]
    sentences = _load(lesson)["sentences"]
    n = next(k for k, s in enumerate(sentences) if s["id"] == sid)
    note = ask(sentences, n, i)
    with LOCK:
        cache = _read_cache(lesson)
        for k in note["words"]:  # 词组里的每个词都指向同一条，点哪个都不用再查
            cache[f"{sid}:{k}"] = note
        _write_cache(lesson, cache)
    return note


def speak(lesson: str, key: str, text: str) -> str:
    """词组、词典里没有的词：用百炼 Emily 现读，存进课程文件夹，返回相对课程目录的路径。"""
    key = " ".join(re.sub(r"[^a-z0-9']", "", t) for t in key.lower().split()).strip()
    if not key:
        raise ValueError("没有要读的词")
    rel = f"tts/{tts.EMILY}/{tts.file_name(key)}"
    path = ROOT / "lessons" / lesson / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(tts.synthesize(tts.spoken(text or key)))
    return rel


def sample(lesson: str, count: int) -> None:
    """随机抽几个词现查，打印出来给 claude 看提示词写得好不好（不进缓存）。"""
    sentences = _load(lesson)["sentences"]
    picks = [(n, i) for n, s in enumerate(sentences) for i, w in enumerate(s["words"]) if w["key"]]
    for n, i in random.sample(picks, count):
        started = time.time()
        note = ask(sentences, n, i)
        print(f"\n第 {sentences[n]['id']} 句｜{sentences[n]['text']}\n  点 {sentences[n]['words'][i]['text']}"
              f"（{time.time() - started:.1f} 秒）→ {json.dumps(note, ensure_ascii=False)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args[:1] == ["sample"]:
        sample(args[1] if len(args) > 1 else "260821", int(args[2]) if len(args) > 2 else 12)
    else:
        print(__doc__)
