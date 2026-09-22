"""用百炼的语音合成给单词生成朗读，存成音频文件。

为什么不用浏览器自带的朗读（2026-09-22 查的）：它用哪个声音随浏览器和系统变。
owner 的 Chrome 用的是 Google UK English Female，是谷歌的联网声音，中国大陆不翻墙读不出来，
违反 demand.md 的网络约束。备课时生成好文件，孩子那边只播放文件，不连任何外部服务。
声音是 owner 2026-09-22 在试听页里选的：Emily · 英音女声（决策 D26）。

- teach.py 建课程文件时调 build()：给词条表里每个词生成一个 mp3，已经有的不重做。
  文件放在 lessons/<课>/tts/<声音>/，换声音就会整套重做。
- 试听：<pywork python> pipeline/tts.py try —— 用几个声音读几个本集的词，写到 lessons/<课>/tts_try/，
  在 http://localhost:8765/lessons/<课>/tts_try/ 打开，还能看出浏览器自带朗读用的是哪个声音。
密钥从 pipeline/keys.py 读，不打印（红线）。
"""

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from keys import read_key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODEL = "cosyvoice-v3-flash"
# 百炼音色列表 https://help.aliyun.com/zh/model-studio/cosyvoice-voice-list
VOICES = {
    "loongemily_v3": "Emily · 英音女声",
    "loongluna_v3": "Luna · 英音女声",
    "loongeric_v3": "Eric · 英音男声",
    "loongluca_v3": "Luca · 英音男声",
    "loongabby_v3": "Abby · 美音女声",
    "loongandy_v3": "Andy · 美音男声",
}
TRY_WORDS = ["finished", "each", "caffeine", "decaf", "alertness", "grumpy"]
VOICE = "loongemily_v3"   # owner 2026-09-22 选的
WORKERS = 2               # 同时发太多会被限流（4 路时常被限流）


def synthesize(text: str, voice: str, tries: int = 5) -> bytes:
    import dashscope
    from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

    dashscope.api_key = read_key("qwen")
    problem = ""
    for k in range(tries):
        try:
            synthesizer = SpeechSynthesizer(model=MODEL, voice=voice, format=AudioFormat.MP3_24000HZ_MONO_256KBPS)
            audio = synthesizer.call(text)
            if audio:
                return audio
            problem = "没有返回声音"
        except Exception as e:  # 网络抖动、限流：等一会儿再试
            problem = type(e).__name__
        time.sleep(2 * 2 ** k)
    raise RuntimeError(f"语音合成连试 {tries} 次都失败（{problem}）：{voice} / {text}")


def file_name(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "_", key) + ".mp3"


def spoken(key: str) -> str:
    """交给语音合成的写法：首字母大写再加句号，当成一句完整的话来读。
    直接给小写的单词，Emily 会把头一个音读坏：drank 听成 rank、need 听成 aid，
    机器耳朵 6 个全错；改成 Drank. 这种写法 6 个全对（2026-09-22 试的）。
    改了这里，要删掉 lessons/<课>/tts/ 让它整套重做——已有的文件不会自动重做。"""
    return key[:1].upper() + key[1:] + "."


def build(lesson_dir: Path, keys: list[str], voice: str = VOICE) -> dict[str, str]:
    """给每个词生成朗读文件，返回 {词: 相对课程目录的路径}。已经有的文件不重做。"""
    folder = lesson_dir / "tts" / voice
    folder.mkdir(parents=True, exist_ok=True)
    todo = [k for k in keys if not (folder / file_name(k)).exists()]
    if todo:
        print(f"  朗读：要新生成 {len(todo)} 个词（{VOICES.get(voice, voice)}）")

        def one(key: str) -> None:
            (folder / file_name(key)).write_bytes(synthesize(spoken(key), voice))

        with ThreadPoolExecutor(WORKERS) as pool:
            list(pool.map(one, todo))
    return {k: f"tts/{voice}/{file_name(k)}" for k in keys}


def try_page(lesson: str) -> None:
    out = ROOT / "lessons" / lesson / "tts_try"
    out.mkdir(parents=True, exist_ok=True)
    for voice in VOICES:
        for word in TRY_WORDS:
            (out / f"{voice}-{word}.mp3").write_bytes(synthesize(word, voice))
        print(f"  {VOICES[voice]}：{len(TRY_WORDS)} 个词")
    page = (Path(__file__).resolve().parent / "tts_try.html").read_text(encoding="utf-8")
    page = page.replace("__DATA__", json.dumps({"voices": VOICES, "words": TRY_WORDS}, ensure_ascii=False))
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"试听页：http://localhost:8765/lessons/{lesson}/tts_try/")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args[:1] == ["try"]:
        try_page(args[1] if len(args) > 1 else "260821")
    else:
        print(__doc__)
