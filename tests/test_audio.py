"""验声音：录下浏览器真正放出来的声音，看每一句的开头结尾对不对。

为什么要有这一份（2026-09-22）：tests/test_player.py 只核对数字——浏览器报告播到第几秒，
和算好的切口对不对得上。它从来没听过放出来的声音。owner 两次听出单词原声带杂音，它都发现不了；
第一次拿这份一查，还查出约 9 句的开头被切掉了（Sugar、Goodbye……），修法见 pipeline/ear_bounds.py。

三层：
1. 录音：在播放器的音量节点后面接一个录音节点，录到的就是要送到扬声器的声音（含渐强渐弱）。
   用的是真的 Chrome（和 owner 一样），调的是点「全文」里一句时的同一个函数：只播这一句。
2. 对时间：把录到的声音和原音频逐个采样比对，算出实际放的是原音频的哪一秒到哪一秒，
   和预定的起止比，看前后有没有多放、少放。
3. 机器耳朵（pipeline/ear.py）：听出来的第一个词、最后一个词对不对——对不上多半是开头被切、结尾被切或带进了别的句子。
   机器耳朵很宽容（-ugar 也听成 Sugar），也有自己的毛病（I've 听成 I），所以最后做一页试听，给人耳抽查。

跑法：<pywork python> tests/test_audio.py [--sentences 20]（默认全部正文）
  要调百炼的识别接口（一集几分钱），不在每次改完都跑的那一份里；改了句子边界或播放器的停法就跑一遍。
  结果写到 lessons/<课>/audio_check/，试听页在 http://localhost:8765/lessons/<课>/audio_check/
"""

import json
import random
import sys
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from ear import hear, words_of  # noqa: E402
from serve import make_server  # noqa: E402

PORT = 8798
LESSON = "260821"
OUT = ROOT / "lessons" / LESSON / "audio_check"
REF_RATE = 16000
OUTSIDE = "片头片尾"

RECORDER = """() => {
  ensureGraph();
  if (window.__rec) return ctx.sampleRate;
  window.__rec = { on: false, data: [] };
  const proc = ctx.createScriptProcessor(2048, 1, 1);
  gain.connect(proc);
  proc.connect(ctx.destination);  // 输出留空，只为了让它跑起来
  proc.onaudioprocess = (e) => { if (__rec.on) __rec.data.push(Array.from(e.inputBuffer.getChannelData(0))); };
  return ctx.sampleRate;
}"""


def load_ref() -> np.ndarray:
    with wave.open(str(ROOT / "lessons" / LESSON / "audio_16k.wav")) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def audible(clip: np.ndarray) -> np.ndarray:
    """去掉前后音量为零的部分（渐强之前、停下之后）。"""
    nz = np.flatnonzero(np.abs(clip) > 1e-6)
    return clip[nz[0]:nz[-1] + 1] if len(nz) else clip[:0]


def locate(body: np.ndarray, rate: int, ref: np.ndarray, t0: float, t1: float) -> tuple[float, float]:
    """录到的声音实际是原音频的哪一秒到哪一秒。"""
    if not len(body):
        return float("nan"), float("nan")
    x = np.interp(np.arange(0, len(body), rate / REF_RATE), np.arange(len(body)), body)
    # 只在预定起止前后 0.15 秒里找：找得太宽，附近有相似的声音就会认错
    lo = max(0, int((t0 - 0.15) * REF_RATE))
    seg = ref[lo:int((t1 + 0.15) * REF_RATE)]
    n = len(seg) + len(x)
    corr = np.fft.irfft(np.fft.rfft(seg, n) * np.conj(np.fft.rfft(x, n)), n)[:len(seg) - len(x) + 1]
    start = (lo + int(np.argmax(corr))) / REF_RATE
    return start, start + len(x) / REF_RATE


def save_wav(path: Path, clip: np.ndarray, rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(clip, -1, 1) * 32767).astype(np.int16).tobytes())


def record(page, action: str) -> np.ndarray:
    """执行一个动作，录下从开始到停住放出来的全部声音。"""
    page.evaluate("__rec.data = []; __rec.on = true")
    page.evaluate(action)
    page.wait_for_function("!audio.paused", timeout=5000)
    page.wait_for_function("audio.paused", timeout=20000)
    page.wait_for_timeout(400)  # 让已经送进声卡队列的声音也录完
    page.evaluate("__rec.on = false")
    data = page.evaluate("__rec.data")
    return np.concatenate([np.array(c, dtype=np.float32) for c in data]) if data else np.zeros(0, np.float32)


def run(page, ref: np.ndarray, count: int | None) -> list[dict]:
    page.goto(f"http://127.0.0.1:{PORT}/web/")
    page.wait_for_function("window.lesson !== null && audio.readyState >= 2", timeout=20000)
    lesson = page.evaluate("lesson")
    rate = page.evaluate(RECORDER)
    body = [i for i, s in enumerate(lesson["sentences"]) if s["speaker"] != OUTSIDE]
    picked = body if count is None else sorted(random.Random(0).sample(body, min(count, len(body))))
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for n, i in enumerate(picked):
        s = lesson["sentences"][i]
        clip = audible(record(page, f"playOne({i})"))
        a, b = locate(clip, rate, ref, s["start"], s["end"])
        name = f"s{s['id']:03d}.wav"
        save_wav(OUT / name, clip, rate)
        results.append({"file": name, "sentence": s["id"], "expect": s["text"],
                        "cut": [s["start"], s["end"]], "played": [a, b]})
        if (n + 1) % 10 == 0 or n + 1 == len(picked):
            print(f"  录了 {n + 1}/{len(picked)} 句")
    return results


def judge(results: list[dict]) -> None:
    with ThreadPoolExecutor(4) as pool:  # 同时发太多会被限流
        heard = list(pool.map(lambda r: hear(OUT / r["file"]), results))
    for r, h in zip(results, heard):
        got, want = words_of(h), words_of(r["expect"])
        r["heard"] = h
        r["early_ms"] = round((r["cut"][0] - r["played"][0]) * 1000)   # 正数：比预定早开始，多放了前面的
        r["late_ms"] = round((r["played"][1] - r["cut"][1]) * 1000)    # 正数：比预定晚结束，多放了后面的
        r["head_ok"] = got[:1] == want[:1]
        r["tail_ok"] = got[-1:] == want[-1:]
        r["all_ok"] = got == want


def write_page(results: list[dict]) -> None:
    rows = []
    for r in results:
        bad = [x for x, ok in (("开头", r["head_ok"]), ("结尾", r["tail_ok"])) if not ok]
        rows.append(
            f"<tr class='{'bad' if bad else 'ok'}'><td>{r['sentence']}</td>"
            f"<td><button onclick=\"play('{r['file']}')\">播放</button></td>"
            f"<td>{r['expect']}</td><td>{r['heard']}</td>"
            f"<td>{r['early_ms']:+d} / {r['late_ms']:+d}</td><td>{'、'.join(bad) + '对不上' if bad else '对'}</td></tr>")
    ok = sum(r["head_ok"] and r["tail_ok"] for r in results)
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>声音检查</title>
<style>body{{background:#111318;color:#f1e8d8;font:14px/1.6 'Microsoft YaHei UI',sans-serif;padding:24px}}
table{{border-collapse:collapse;width:100%}}td,th{{border-top:1px solid #333;padding:6px 8px;text-align:left}}
tr.bad td:last-child{{color:#ef8b73}}tr.ok td:last-child{{color:#62c1b9}}button{{cursor:pointer}}</style></head>
<body><h1>声音检查：录下浏览器真正放出来的每一句</h1>
<p>开头结尾都对得上 {ok} / {len(results)} 句。「前后多放」是实际放出来的比预定起止早开始、晚结束多少毫秒（负数是少放）。
机器耳朵很宽容，也有自己的毛病（I've 常听成 I），「对不上」的请用耳朵听一下，「对」的也请抽几条。</p>
<table><tr><th>句</th><th></th><th>应该听到</th><th>机器听到</th><th>前后多放（毫秒）</th><th>开头结尾</th></tr>
{''.join(rows)}</table>
<script>let a=null;function play(f){{if(a)a.pause();a=new Audio(f);a.play();}}</script></body></html>"""
    (OUT / "index.html").write_text(html, encoding="utf-8")
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    count = int(sys.argv[sys.argv.index("--sentences") + 1]) if "--sentences" in sys.argv else None
    server = make_server(PORT)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ref = load_ref()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True,
                                    args=["--autoplay-policy=no-user-gesture-required"])
        page = browser.new_page()
        try:
            results = run(page, ref, count)
        finally:
            browser.close()
            server.shutdown()
    print("机器耳朵在听……")
    judge(results)
    write_page(results)
    print(f"{len(results)} 句：放出来的时间和预定差不到 50 毫秒的 "
          f"{sum(abs(r['early_ms']) <= 50 and abs(r['late_ms']) <= 50 for r in results)} 句；"
          f"机器听到的第一个词对的 {sum(r['head_ok'] for r in results)} 句，最后一个词对的 {sum(r['tail_ok'] for r in results)} 句")
    for r in results:
        if not (r["head_ok"] and r["tail_ok"]):
            print(f"  第 {r['sentence']} 句｜应该：{r['expect']}｜听到：{r['heard']}")
    print(f"试听页：http://localhost:8765/lessons/{LESSON}/audio_check/")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
