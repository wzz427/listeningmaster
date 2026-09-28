"""点词看的讲解。分两步（owner 2026-09-22，决策 D30）：
- 那一行（词性、英式音标、这句里的中文意思）：备课时整句一起写好，存进 lesson.json 每句的 notes，点词马上出来；
  备课漏了的词，点了再单个补查。
- 展开的（常见意思、搭配、例句）：孩子点了「展开」才查（决策 D29）——点展开的比点词的更少，不该每个词都写。
词组和词典里没有的词的朗读，也是点了才现读。

由 pipeline/teach.py（备课时的 prepare）和 pipeline/serve.py 的 /api/explain、/api/more、/api/speak 调；
密钥只在本地服务里，网页里没有（以后上服务器，放网关）。
点了才查的存在 lessons/<课>/explain_cache.json，同一处再点、别的孩子点同一处都直接返回。

讲得好不好靠提示词（owner：不挑错，不给孩子标「电脑生成」，写对提示词就行）。
改了那一行的提示词，跑 teach.py <课> --renote 重写（只重写这一项，翻译、分段不动）；改了展开的，删掉 explain_cache.json 就会按新的重新查。
抽查用：<pywork python> pipeline/explain.py sample [课] [句数] [--more]
"""

import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import call  # noqa: E402
import tts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODEL = "deepseek-flash"   # 不开思考模式（llm.call 里关的），一次不到一秒
WORKERS = 8                # 备课时几句同时问
LOCK = threading.Lock()

WHO = "你在帮一个刚通过剑桥 PET（B1）、听力偏弱的中国初中生听英语。"

# 那一行怎么写：备课时整句写、点词时单个补查，用同一套规则。
# owner 2026-09-22：原来那句「这句里……」都在复述句子，没有意义；改成词典那样一行：词性、音标、简单的中文意思
RULES = """1. 先看词是不是和旁边的词组成固定说法：短语动词（cut down on、give up）、固定词组（at the moment、a bit、first thing in the morning）、打招呼之类的套话（How are you、That's it、Oh well）。是的话整个词组写一条，words 写词组里每个词的序号，text 写整个词组；不是就一个词一条，words 只写它自己的序号。
   几个词合起来的名字（Real Easy English、BBC Learning English）也写成一条。同一个词重复说了两遍（decaf, decaf）不是词组，各写各的。
2. pos：词性，按它在这句里的用法定，用中国词典的写法：n. v. adj. adv. prep. conj. pron. num. art. int. aux.（finished 在 I've finished my coffee 里是 v.）。词组写「词组」；人名、地名、节目名写「名字」；I've、that's、don't 这类缩写写「缩写」；不定式里的 to（want to go）写「不定式」。
3. ipa：英式音标，和牛津、剑桥词典里的英音一样，前后加斜线，两个音节以上标重音。注句子里的这个形式（finished 注 /ˈfɪnɪʃt/，不注 finish）。词组注整个词组。
4. zh：它在这句里的中文意思，像词典的释义，不超过 10 个字。只写这个词的意思，不复述句子，不说这句在讲什么。一个词有几个意思时只写这句用的那个。
   缩写写完整写法再跟中文，如「= I have 我已经」。不定式里的 to 写「不用翻译」。人名不译成中文，写「人名（主持人）」这样说清是谁；节目名、网站名写它是什么，如「节目名」。
5. more：值不值得展开看常见意思、搭配和例句。名字写 false，别的都写 true。"""

LINES = WHO + """下面是他要听的一句话（前后句只作背景）。给这句里的每个词写一行像词典那样的解释，他点哪个词就显示哪一行。按下面写：
""" + RULES + """
每个序号都要写到，而且只能出现在一条里。

例子：句子 You take your coffee black.，输出
{"items":[{"words":[0],"text":"You","pos":"pron.","ipa":"/juː/","zh":"你","more":true},{"words":[1],"text":"take","pos":"v.","ipa":"/teɪk/","zh":"喝（咖啡、茶）","more":true},{"words":[2],"text":"your","pos":"pron.","ipa":"/jɔː(r)/","zh":"你的","more":true},{"words":[3],"text":"coffee","pos":"n.","ipa":"/ˈkɒfi/","zh":"咖啡","more":true},{"words":[4],"text":"black","pos":"adj.","ipa":"/blæk/","zh":"（咖啡）不加奶的","more":true}]}
句子 She gave up sugar.，输出
{"items":[{"words":[0],"text":"She","pos":"pron.","ipa":"/ʃiː/","zh":"她","more":true},{"words":[1,2],"text":"gave up","pos":"词组","ipa":"/ɡeɪv ʌp/","zh":"戒掉","more":true},{"words":[3],"text":"sugar","pos":"n.","ipa":"/ˈʃʊɡə(r)/","zh":"糖","more":true}]}

只输出 JSON：{"items":[...]}"""

LINE = WHO + """他听的时候点了句子里的一个词，要看一行像词典那样的解释。只写他点的这个词（或它所在的词组）这一条。按下面写：
""" + RULES + """

例子：句子 She gave up sugar. 点了 up（序号 2），输出
{"words":[1,2],"text":"gave up","pos":"词组","ipa":"/ɡeɪv ʌp/","zh":"戒掉","more":true}

只输出 JSON：{"words":[序号],"text":"...","pos":"...","ipa":"/.../","zh":"...","more":true 或 false}"""

# 点「展开」才查
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


def _cache_path(lesson: str, root: Path | None = None) -> Path:
    return (root or ROOT / "lessons") / lesson / "explain_cache.json"


def _read_cache(lesson: str, root: Path | None = None) -> dict:
    path = _cache_path(lesson, root)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_cache(lesson: str, cache: dict, root: Path | None = None) -> None:
    _cache_path(lesson, root).write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def _load(lesson: str, root: Path | None = None) -> dict:
    return json.loads(((root or ROOT / "lessons") / lesson / "lesson.json").read_text(encoding="utf-8"))


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
            "after": sentences[n + 1]["text"] if n + 1 < len(sentences) else "",
            "words": [{"i": k, "w": _bare(w)} for k, w in enumerate(sentences[n]["words"])]}


def _note(s: dict, data: dict, clicked: int | None = None) -> dict | None:
    """把模型写的一条整理好；序号不对的返回 None（备课时丢掉，点了再补查）。"""
    words = {k for k in data.get("words") or [] if isinstance(k, int) and 0 <= k < len(s["words"])}
    if clicked is not None:
        words.add(clicked)
    if not words:
        return None
    words = sorted(words)
    if max(words) - min(words) > 5:  # 拼得太远的不当词组
        if clicked is None:
            return None
        words = [clicked]
    text = (data.get("text") or "").strip() if len(words) > 1 else ""
    ipa = (data.get("ipa") or "").strip().strip("/[] ")
    return {"words": words, "text": text or _bare(s["words"][words[0]]), "pos": (data.get("pos") or "").strip(),
            "ipa": f"/{ipa}/" if ipa else "", "zh": (data.get("zh") or "").strip(),
            "more": data.get("more") is not False}


def lines_for(sentences: list[dict], n: int) -> list[dict]:
    """备课时：给第 n 句的每个词写那一行。一个词只归一条；漏掉的词点了再补查。"""
    s = sentences[n]
    notes, taken = [], set()
    for item in _ask(LINES, _context(sentences, n)).get("items") or []:
        note = _note(s, item) if isinstance(item, dict) else None
        if note and note["zh"] and not taken & set(note["words"]):
            taken |= set(note["words"])
            notes.append(note)
    return notes


def prepare(sentences: list[dict], known: dict[str, list]) -> dict[str, list]:
    """备课时给每句写好那一行，返回 {英文句子: notes}。known 是上一版写过的，句子没变就沿用。"""
    todo = [n for n, s in enumerate(sentences) if s["text"] not in known]
    started = time.time()
    with ThreadPoolExecutor(WORKERS) as pool:
        fresh = dict(zip((sentences[n]["text"] for n in todo), pool.map(lambda n: lines_for(sentences, n), todo)))
    out = {s["text"]: known.get(s["text"]) or fresh.get(s["text"]) or [] for s in sentences}
    words = sum(len(s["words"]) for s in sentences)
    covered = sum(len(x["words"]) for s in sentences for x in out[s["text"]])
    print(f"  每个词的那一行：新写 {len(todo)} 句、沿用 {len(sentences) - len(todo)} 句，{time.time() - started:.0f} 秒；"
          f"{words} 个词里写到 {covered} 个，漏的点了再补查")
    return out


def ask(sentences: list[dict], n: int, i: int) -> dict:
    """点词时补查：备课漏了第 n 句的第 i 个词，单独给它写那一行。"""
    note = _note(sentences[n], _ask(LINE, {**_context(sentences, n), "clicked": i}), i)
    assert note is not None  # 带着点的那个序号，总会有一条
    return note


def ask_more(sentences: list[dict], n: int, note: dict) -> dict:
    """调模型写展开的内容：常见意思（标出这句用的第几个）、搭配、例句。"""
    data = _ask(MORE, {**_context(sentences, n), "word": note["text"], "pos": note["pos"], "zh": note["zh"]})
    senses = [str(x).strip() for x in data.get("senses") or [] if str(x).strip()]
    used = data.get("used")
    return {"senses": senses, "used": used if isinstance(used, int) and 1 <= used <= len(senses) else None,
            "collocations": [c for c in data.get("collocations") or [] if isinstance(c, dict) and c.get("en")],
            "example": data.get("example") if isinstance(data.get("example"), dict) else None}


def _where(lesson: str, sid: int, root: Path | None = None) -> tuple[list[dict], int]:
    sentences = _load(lesson, root)["sentences"]
    return sentences, next(k for k, s in enumerate(sentences) if s["id"] == sid)


def _store(lesson: str, sid: int, note: dict, root: Path | None = None) -> None:
    with LOCK:
        cache = _read_cache(lesson, root)
        for k in note["words"]:  # 词组里的每个词都指向同一条，点哪个都不用再查
            cache[f"{sid}:{k}"] = note
        _write_cache(lesson, cache, root)


def explain(lesson: str, sid: int, i: int, root: Path | None = None) -> dict:
    """第 sid 句第 i 个词的那一行：查过的（展开过的连展开的一起）→ 备课时写好的 → 现在补查。
    root：课目录的根（对外模式传该账号的 lessons 目录，SPEC-009；不传用仓库的 lessons/）。"""
    with LOCK:
        note = _read_cache(lesson, root).get(f"{sid}:{i}")
    if note:
        return note
    sentences, n = _where(lesson, sid, root)
    note = next((x for x in sentences[n].get("notes") or [] if i in x["words"]), None)
    if note:
        return note
    note = ask(sentences, n, i)
    _store(lesson, sid, note, root)
    return note


def explain_more(lesson: str, sid: int, i: int, root: Path | None = None) -> dict:
    """点了「展开」：第 sid 句第 i 个词的常见意思、搭配、例句。"""
    note = explain(lesson, sid, i, root=root)
    if note.get("detail"):
        return note["detail"]
    sentences, n = _where(lesson, sid, root)
    note = {**note, "detail": ask_more(sentences, n, note)}
    _store(lesson, sid, note, root)
    return note["detail"]


def speak(lesson: str, key: str, text: str, root: Path | None = None) -> str:
    """词组、词典里没有的词：用百炼 Emily 现读，存进课程文件夹，返回相对课程目录的路径。"""
    key = " ".join(re.sub(r"[^a-z0-9']", "", t) for t in key.lower().split()).strip()
    if not key:
        raise ValueError("没有要读的词")
    rel = f"tts/{tts.EMILY}/{tts.file_name(key)}"
    path = (root or ROOT / "lessons") / lesson / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(tts.synthesize(tts.spoken(text or key)))
    return rel


def sample(lesson: str, count: int, more: bool) -> None:
    """随机抽几句重新写那一行，打印出来给 claude 看提示词写得好不好（不存）。加 --more 每句再抽一个词查展开的。"""
    sentences = _load(lesson)["sentences"]
    for n in random.sample(range(len(sentences)), count):
        started = time.time()
        notes = lines_for(sentences, n)
        print(f"\n第 {sentences[n]['id']} 句｜{sentences[n]['text']}（{time.time() - started:.1f} 秒）")
        for x in notes:
            print(f"  {x['text']}  {x['pos']}  {x['ipa']}  {x['zh']}{'' if x['more'] else '  （不展开）'}")
        if more and notes:
            note = random.choice(notes)
            started = time.time()
            detail = ask_more(sentences, n, note)
            print(f"  展开 {note['text']}（{time.time() - started:.1f} 秒）→ {json.dumps(detail, ensure_ascii=False)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args[:1] == ["sample"]:
        sample(args[1] if len(args) > 1 else "260821", int(args[2]) if len(args) > 2 else 5, "--more" in sys.argv)
    else:
        print(__doc__)
