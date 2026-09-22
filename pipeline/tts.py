"""用百炼的语音合成给单词生成朗读，存成音频文件。

为什么不用浏览器自带的朗读（2026-09-22 查的）：它用哪个声音随浏览器和系统变。
Chrome 挑中的英音是谷歌的联网声音，中国大陆不翻墙多半没声音，违反 demand.md 的网络约束。
备课时生成好文件，孩子那边只播放文件，不连任何外部服务。

现在只有试听：<pywork python> pipeline/tts.py try
  用几个声音读几个本集的词，写到 lessons/<课>/tts_try/，配一个试听页，
  在 http://localhost:8765/lessons/<课>/tts_try/ 打开。试听页里还能测浏览器自带朗读用的是哪个声音。
密钥从 pipeline/keys.py 读，不打印（红线）。
"""

import json
import sys
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


def synthesize(text: str, voice: str) -> bytes:
    import dashscope
    from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

    dashscope.api_key = read_key("qwen")
    synthesizer = SpeechSynthesizer(model=MODEL, voice=voice, format=AudioFormat.MP3_24000HZ_MONO_256KBPS)
    audio = synthesizer.call(text)
    if not audio:
        raise RuntimeError(f"语音合成没有返回声音：{voice} / {text}")
    return audio


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
