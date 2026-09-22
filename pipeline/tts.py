"""单词和词组的朗读，提前存成文件（决策 D27）。

规则（owner 2026-09-22 定的）：单个词用本地发音词典里的谷歌英音；词典里没有的词、还有词组，用百炼 Emily 读。
这样备课时不用翻墙，孩子那边只放文件。

为什么是谷歌（2026-09-22 owner 在对比页里听了 Emily / 谷歌 / 有道三种选的）：
百炼 Emily 读单个词语调怪，头一个音也常读错（each 读成 H、cups 读成 Pups）。
谷歌翻译的朗读就是 Python 库 gTTS 用的那个（它生成的英音文件和这里取的逐字节相同），不装那个库，直接取。
它要翻墙才取得到，孩子那边又不许依赖境外服务（demand.md 的网络约束），所以：

- 发音词典：放在仓库外、和仓库并排的 WordsAudio/，常用 2 万词一次取好，以后备课不用翻墙。
  <pywork python> pipeline/tts.py library [--top 20000]    断了重跑会接着取，已有的不重取
  词表用 wordfreq 的常见程度排名（综合字幕、书、网页、维基百科），收的是实际出现的形式，finished、cups 也算。
  光靠常见程度盖不住每集教的词：decaf 排第 4.5 万、phrasal 排第 9 万。
- 每集的朗读：teach.py 建课程文件时调 build()，把这集用到的词从词典拷到 lessons/<课>/tts/（拷几百个文件，一两秒）。
- 词典里没有的词和词组：孩子点了「听朗读」才交给百炼 Emily（cosyvoice-v3-flash，owner 之前在 6 个声音里选的）现读，
  存进课程文件夹，下次直接放（pipeline/explain.py 的 speak）。Emily 读单个词语调怪，只给词典里没有的词兜底；读词组自然得多。
- 抽听：<pywork python> pipeline/tts.py check —— 每集建完跑一次，写到 lessons/<课>/tts_check/，
  点着听、把读得不对的标出来（机器耳朵先听一遍，它听着不对的排前面）。

谷歌翻译的朗读是它网页用的接口，不是公开的正式接口：家里和熟人之间用；要公开发布得换正式的付费接口。
"""

import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = ROOT.parent / "WordsAudio"   # 和仓库并排；两个文件夹一起拷走就能用
LABEL = "单词：谷歌翻译英音；词组和词典里没有的词：百炼 Emily 英音"
WORKERS = 4                            # 4 路时 60 个词 11 秒、一个没失败（2026-09-22 试的）
# 谷歌什么都读，拼不出来的乱码它也一个字母一个字母念
SOURCES = {"google_en-GB": lambda w: "https://translate.google.com/translate_tts?" + urllib.parse.urlencode(
    {"ie": "UTF-8", "tl": "en-GB", "client": "tw-ob", "q": w})}
FIRST = "google_en-GB"
EMILY = "bailian_emily"
EMILY_MODEL, EMILY_VOICE = "cosyvoice-v3-flash", "loongemily_v3"
WORD = re.compile(r"[a-z]+(?:['-][a-z]+)*")


def file_name(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "_", key) + ".mp3"


def fetch(source: str, word: str, tries: int = 3) -> bytes | None:
    """取一个词的朗读；取不到（没网、被拦、对方不认识这个词）返回 None。"""
    for k in range(tries):
        try:
            req = urllib.request.Request(SOURCES[source](word), headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read()
                if r.headers.get("Content-Type", "").startswith("audio") and len(body) > 1000:
                    return body
                return None
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return None
        except OSError:  # 没网、超时：等一会儿再试
            pass
        time.sleep(1 + 2 * k)
    return None


def in_library(source: str, key: str) -> Path | None:
    path = LIBRARY / source / file_name(key)
    return path if path.exists() else None


def save(source: str, key: str, body: bytes) -> Path:
    path = LIBRARY / source / file_name(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def library(top: int) -> None:
    """把常用的 top 个词的谷歌朗读取进发音词典。"""
    from wordfreq import top_n_list

    words = [w for w in top_n_list("en", top * 2) if WORD.fullmatch(w)][:top]
    todo = [w for w in words if not in_library(FIRST, w)]
    print(f"词典：{LIBRARY}；常用 {len(words)} 个词，已有 {len(words) - len(todo)} 个，要取 {len(todo)} 个")
    failed, started = [], time.time()

    def one(word: str) -> None:
        body = fetch(FIRST, word)
        if body:
            save(FIRST, word, body)
        else:
            failed.append(word)

    with ThreadPoolExecutor(WORKERS) as pool:
        for n, _ in enumerate(pool.map(one, todo), 1):
            if n % 500 == 0:
                print(f"  {n}/{len(todo)}，{time.time() - started:.0f} 秒，失败 {len(failed)}", flush=True)
    (LIBRARY / "words.txt").write_text("\n".join(words) + "\n", encoding="utf-8")
    (LIBRARY / "README.txt").write_text(
        "单词发音词典：谷歌翻译的英音朗读，一个词一个 mp3。\n"
        "由 ListeningMaster/pipeline/tts.py 生成：tts.py library 取常用词（words.txt），要翻墙；备课时词典里没有的词改用百炼 Emily 读。\n"
        "google_en-GB/ 里一个词一个 mp3，文件名是词里的非字母数字换成下划线。\n"
        "只在家里和熟人之间用，不公开传播。\n", encoding="utf-8")
    print(f"取完：成功 {len(todo) - len(failed)} 个，失败 {len(failed)} 个" + (f"：{failed[:20]}" if failed else ""))


def synthesize(text: str, tries: int = 5) -> bytes:
    """百炼 Emily 读一段英文。密钥从 pipeline/keys.py 读，不打印（红线）。"""
    import dashscope
    from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer
    from keys import read_key

    dashscope.api_key = read_key("qwen")
    problem = ""
    for k in range(tries):
        try:
            audio = SpeechSynthesizer(model=EMILY_MODEL, voice=EMILY_VOICE,
                                      format=AudioFormat.MP3_24000HZ_MONO_256KBPS).call(text)
            if audio:
                return audio
            problem = "没有返回声音"
        except Exception as e:  # 网络抖动、限流：等一会儿再试
            problem = type(e).__name__
        time.sleep(2 * 2 ** k)
    raise RuntimeError(f"语音合成连试 {tries} 次都失败（{problem}）：{text}")


def spoken(text: str) -> str:
    """交给 Emily 的写法：首字母大写，末尾没有标点就加句号，当成一句完整的话来读。
    直接给小写的单词，Emily 会把头一个音读坏：drank 听成 rank、need 听成 aid（2026-09-22 试的）。"""
    text = text.strip()
    return text[:1].upper() + text[1:] + ("" if text[-1:] in ".?!" else ".")


def build(lesson_dir: Path, words: list[str]) -> dict[str, str]:
    """备课时把这集用到的词从发音词典拷进课程文件夹，返回 {词: 相对课程目录的路径}。
    词典里没有的词不在里面：孩子点了才让 Emily 现读（pipeline/explain.py 的 speak），备课不等它。"""
    out = {}
    for key in words:
        if path := in_library(FIRST, key):
            target = lesson_dir / "tts" / FIRST / file_name(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copyfile(path, target)
            out[key] = f"tts/{FIRST}/{file_name(key)}"
    missing = [k for k in words if k not in out]
    print(f"  朗读：词典里有 {len(out)} 个，拷进课程文件夹；没有的 {len(missing)} 个点了再读" +
          (f"（{'、'.join(missing[:12])}{'……' if len(missing) > 12 else ''}）" if missing else ""))
    return out


def check_page(lesson: str) -> None:
    """给 owner 一页抽听朗读：机器耳朵先听一遍，它听着不对的排前面。
    机器耳朵单听一个词不可靠（to 听成 two、know 听成 no，2026-09-22），只用来排先后，好不好由人耳定。"""
    from ear import hear, words_of

    lesson_dir = ROOT / "lessons" / lesson
    data = json.loads((lesson_dir / "lesson.json").read_text(encoding="utf-8"))
    files, glossary = data["tts"]["files"], data["glossary"]
    keys = sorted(files)
    with ThreadPoolExecutor(4) as pool:
        heard = list(pool.map(lambda k: hear(lesson_dir / files[k]), keys))
    items = [{"key": k, "file": f"../{files[k]}", "zh": glossary.get(k, {}).get("zh", ""),
              "heard": h, "ok": words_of(h) == words_of(k)} for k, h in zip(keys, heard)]
    out = lesson_dir / "tts_check"
    out.mkdir(exist_ok=True)
    page = (Path(__file__).resolve().parent / "tts_check.html").read_text(encoding="utf-8")
    page = page.replace("__DATA__", json.dumps({"voice": data["tts"]["voice"], "items": items}, ensure_ascii=False))
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"机器耳朵听着不对的 {sum(not x['ok'] for x in items)} 个 / 共 {len(items)} 个")
    print(f"抽听页：http://localhost:8765/lessons/{lesson}/tts_check/")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args[:1] == ["library"]:
        library(int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 20000)
    elif args[:1] == ["check"]:
        check_page(args[1] if len(args) > 1 else "260821")
    else:
        print(__doc__)
