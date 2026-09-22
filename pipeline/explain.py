"""孩子点词时现查。分两步：点词只查一行（词性、英式音标、这句里的中文意思），点「展开」才查常见意思、搭配、例句；
词组和词典里没有的词现读。

为什么点了才查（owner 2026-09-22，决策 D29）：一份材料几千个词，孩子真正点的也就十来个，
不该在备课时把每个词都讲一遍；备课要快，几分钟以内。展开的更少，所以详细的也等点了展开再查（决策 D30）。
由 pipeline/serve.py 的 /api/explain、/api/more、/api/speak 调；密钥只在本地服务里，网页里没有（以后上服务器，放网关）。
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

WHO = "你在帮一个刚通过剑桥 PET（B1）、听力偏弱的中国初中生听英语。"

# 第一步：点词就出来的一行。owner 2026-09-22：原来那句「这句里……」都在复述句子，没有意义；
# 改成词典那样一行：词性、音标、简单的中文意思
LINE = WHO + """他听的时候点了句子里的一个词，要看一行像词典那样的解释。按下面写：
1. 先看点的这个词是不是和旁边的词组成固定说法：短语动词（cut down on、give up）、固定词组（at the moment、a bit、first thing in the morning）、打招呼之类的套话（How are you、That's it、Oh well）。是的话讲整个词组，words 写词组里每个词的序号，text 写整个词组；不是就只讲这个词，words 只写它自己的序号。
2. pos：词性，按它在这句里的用法定，用中国词典的写法：n. v. adj. adv. prep. conj. pron. num. art. int. aux.（finished 在 I've finished my coffee 里是 v.）。词组写「词组」；人名、地名、节目名写「名字」；I've、that's、don't 这类缩写写「缩写」。
3. ipa：英式音标，和牛津、剑桥词典里的英音一样，前后加斜线，两个音节以上标重音。注句子里的这个形式（finished 注 /ˈfɪnɪʃt/，不注 finish）。词组注整个词组。
4. zh：它在这句里的中文意思，像词典的释义，不超过 10 个字。只写这个词的意思，不复述句子，不说这句在讲什么。一个词有几个意思时只写这句用的那个。
   缩写写完整写法再跟中文，如「= I have」。人名写中文译名，括号里说是谁，如「尼尔（主持人）」。
5. more：值不值得展开看常见意思、搭配和例句。名字写 false，别的都写 true。

例子：句子 You take your coffee black. 点了 black（序号 4），输出
{"words":[4],"text":"black","pos":"adj.","ipa":"/blæk/","zh":"（咖啡）不加奶的","more":true}
句子 I gave up sugar last year. 点了 up（序号 2），输出
{"words":[1,2],"text":"gave up","pos":"词组","ipa":"/ɡeɪv ʌp/","zh":"戒掉","more":true}

只输出 JSON：{"words":[序号],"text":"...","pos":"...","ipa":"/.../","zh":"...","more":true 或 false}"""

# 第二步：点「展开」才查
MORE = WHO + """他点了句子里的一个词（或词组），看过了它在这句里的意思，又点了「展开」想多了解一点。
给你句子、前后句、这个词（词组）和它在这句里的意思（zh）。按下面写：
- senses：这个词（词组）最常用的意思，1 到 3 个，每个不超过 12 个字，按常用程度排。只写中学生常会遇到的真实意思，拿不准的不写，宁少勿错。
  每个意思都要真能放进一句常见的英文里用；别把近义词的意思安到它头上（「讲某种语言」是 speak，不是 say），
  也别把搭配、用量当成一个意思（「一勺糖」不是 sugar 的意思）。只有一个常见意思就只写一个。
  冠词、代词、介词、连词、be 动词这类虚词，senses 写它最常见的用法（of 写「……的」）。
- used：这句用的是 senses 里的第几个（从 1 数）。这句里的意思一定要在 senses 里。
- collocations：这句这个意思最常见的搭配 2 到 3 个，英文加中文，英文要是英语母语的人真会这么说的。
- example：一个新例句，别照抄原句，用 B1 学生认识的词，不超过 12 个词，英文加中文。
中文要口语、简单，少用语法术语，孩子是初中生。

例子：句子 You take your coffee black.，词 black，这句里的意思「（咖啡）不加奶的」，输出
{"senses":["黑色的","（咖啡）不加奶的"],"used":2,"collocations":[{"en":"black coffee","zh":"黑咖啡"},{"en":"drink it black","zh":"不加奶喝"}],"example":{"en":"I always have my tea black.","zh":"我喝茶从来不加奶。"}}

只输出 JSON：{"senses":[...],"used":数字,"collocations":[{"en":"...","zh":"..."}],"example":{"en":"...","zh":"..."}}"""


def _cache_path(lesson: str) -> Path:
    return ROOT / "lessons" / lesson / "explain_cache.json"


def _read_cache(lesson: str) -> dict:
    path = _cache_path(lesson)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_cache(lesson: str, cache: dict) -> None:
    _cache_path(lesson).write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def _load(lesson: str) -> dict:
    return json.loads((ROOT / "lessons" / lesson / "lesson.json").read_text(encoding="utf-8"))


def _bare(word: dict) -> str:
    return word["text"].strip(".,?!;:\"")


def _ask(prompt: str, payload: dict) -> dict:
    for _ in range(2):  # 偶尔返回的 JSON 不完整，再要一次
        try:
            return call(MODEL, prompt, json.dumps(payload, ensure_ascii=False))[0]
        except ValueError:
            pass
    return call(MODEL, prompt, json.dumps(payload, ensure_ascii=False))[0]


def _context(sentences: list[dict], n: int) -> dict:
    return {"before": sentences[n - 1]["text"] if n else "",
            "sentence": sentences[n]["text"],
            "after": sentences[n + 1]["text"] if n + 1 < len(sentences) else ""}


def ask(sentences: list[dict], n: int, i: int) -> dict:
    """调模型给第 n 句的第 i 个词写一行：词性、音标、这句里的意思。"""
    s = sentences[n]
    data = _ask(LINE, {**_context(sentences, n),
                       "words": [{"i": k, "w": _bare(w)} for k, w in enumerate(s["words"])], "clicked": i})
    words = sorted({int(k) for k in data.get("words") or [] if 0 <= int(k) < len(s["words"])} | {i})
    if max(words) - min(words) > 5:  # 拼得太远的不当词组
        words = [i]
    text = (data.get("text") or "").strip() if len(words) > 1 else ""
    ipa = (data.get("ipa") or "").strip().strip("/[] ")
    return {"words": words, "text": text or _bare(s["words"][i]), "pos": (data.get("pos") or "").strip(),
            "ipa": f"/{ipa}/" if ipa else "", "zh": (data.get("zh") or "").strip(),
            "more": data.get("more") is not False}


def ask_more(sentences: list[dict], n: int, note: dict) -> dict:
    """调模型写展开的内容：常见意思（标出这句用的第几个）、搭配、例句。"""
    data = _ask(MORE, {**_context(sentences, n), "word": note["text"], "pos": note["pos"], "zh": note["zh"]})
    senses = [str(x).strip() for x in data.get("senses") or [] if str(x).strip()]
    used = data.get("used")
    return {"senses": senses, "used": used if isinstance(used, int) and 1 <= used <= len(senses) else None,
            "collocations": [c for c in data.get("collocations") or [] if isinstance(c, dict) and c.get("en")],
            "example": data.get("example") if isinstance(data.get("example"), dict) else None}


def _where(lesson: str, sid: int) -> tuple[list[dict], int]:
    sentences = _load(lesson)["sentences"]
    return sentences, next(k for k, s in enumerate(sentences) if s["id"] == sid)


def _store(lesson: str, sid: int, note: dict) -> None:
    with LOCK:
        cache = _read_cache(lesson)
        for k in note["words"]:  # 词组里的每个词都指向同一条，点哪个都不用再查
            cache[f"{sid}:{k}"] = note
        _write_cache(lesson, cache)


def explain(lesson: str, sid: int, i: int) -> dict:
    """第 sid 句第 i 个词的那一行；查过的直接返回（展开过的连展开的一起带上）。"""
    with LOCK:
        note = _read_cache(lesson).get(f"{sid}:{i}")
    if note:
        return note
    sentences, n = _where(lesson, sid)
    note = ask(sentences, n, i)
    _store(lesson, sid, note)
    return note


def explain_more(lesson: str, sid: int, i: int) -> dict:
    """点了「展开」：第 sid 句第 i 个词的常见意思、搭配、例句。"""
    note = explain(lesson, sid, i)
    if note.get("detail"):
        return note["detail"]
    sentences, n = _where(lesson, sid)
    note = {**note, "detail": ask_more(sentences, n, note)}
    _store(lesson, sid, note)
    return note["detail"]


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


def sample(lesson: str, count: int, more: bool) -> None:
    """随机抽几个词现查，打印出来给 claude 看提示词写得好不好（不进缓存）。加 --more 连展开的一起查。"""
    sentences = _load(lesson)["sentences"]
    picks = [(n, i) for n, s in enumerate(sentences) for i, w in enumerate(s["words"]) if w["key"]]
    for n, i in random.sample(picks, count):
        started = time.time()
        note = ask(sentences, n, i)
        spent = time.time() - started
        print(f"\n第 {sentences[n]['id']} 句｜{sentences[n]['text']}\n  点 {sentences[n]['words'][i]['text']}"
              f"（{spent:.1f} 秒）→ {note['text']}  {note['pos']}  {note['ipa']}  {note['zh']}"
              f"{'' if note['more'] else '  （不展开）'}")
        if more and note["more"]:
            started = time.time()
            detail = ask_more(sentences, n, note)
            print(f"  展开（{time.time() - started:.1f} 秒）→ {json.dumps(detail, ensure_ascii=False)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args[:1] == ["sample"]:
        sample(args[1] if len(args) > 1 else "260821", int(args[2]) if len(args) > 2 else 12, "--more" in sys.argv)
    else:
        print(__doc__)
