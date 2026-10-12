"""口语实验页的服务端（owner 2026-10-12 拍板做实验，决策 D52）。

干什么：给 web/speak-lab.html 当三样东西——
1. 静态页（8770 端口，只此一页加字体，不带密钥）；
2. 出题：/api/lessons 列已有的课，/api/prompt 用 lessons/<课>/lesson.json 拼陪练的系统提示
   （话题、分段、关键词、教学规矩都在服务端拼好，网页只管发）；
3. 桥（8771 端口 WebSocket）：网页 ⇄ 百炼 Realtime 接口原样转发。密钥只在这一个进程里
   （红线：不打印、不进日志、不进报错；上游握手失败只回状态码和一句人话）。

为什么单独一个程序、不并进 serve.py：这是实验（D52），不能碰播放器和等 owner 复验的
对外版一行代码；实验黄了整个文件删掉就走。

两个模型（A/B 并排，owner 2026-10-12 定）：
- qwen3.8-omni-flash-realtime（全模态 3.8，全双工、可打断、语义 VAD）
- qwen-audio-3.1-realtime-plus（语音专线 3.1，共情与对话节奏见长）
mock 是假模型：不连百炼、不花钱，把整条事件链演一遍，给界面和桥做冒烟检查。

用法：<pywork python> pipeline/speak_lab.py            （起服务：http://localhost:8770/ ）
      <pywork python> pipeline/speak_lab.py --selftest omni38|audio31
                                                       （连真模型各测一次：放一段课程的音频
                                                        进去，看回话和声音出不出得来，约半分钟）
"""

import asyncio
import base64
import json
import math
import sys
import threading
import time
import wave
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import keys  # noqa: E402

HTTP_PORT = 8770
WS_PORT = 8771
MAX_SESSION_SECONDS = 660          # 单次对话硬上限 11 分钟（页面按 10 分钟提醒），到点服务端收线
SELFTEST_SECONDS = 22              # --selftest 最多等这么久就出报告
LESSON_NAME_MAXLEN = 64

# 模型名（网页只传 key，不许把任意模型名拼进 URL）
MODELS = {
    "omni38":  {"id": "qwen3.8-omni-flash-realtime", "voice": "Tina"},
    "audio31": {"id": "qwen-audio-3.1-realtime-plus", "voice": "longanqian_v3.1"},
    "mock":    {"id": "mock", "voice": "mock"},
}

# 百炼 Realtime 的接入地址有两代：新的要绑业务空间（wss://<业务空间id>.cn-beijing.maas.aliyuncs.com），
# 旧的走 dashscope.aliyuncs.com。业务空间 id 不是密钥，但按密钥的规矩一起放在 api-keys.txt
# 的 #qwen-workspace 段里（没有这段就只试旧地址）。
LEGACY_WS = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model={model_id}"
WORKSPACE_WS = "wss://{workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model={model_id}"

PROFILES = {
    "kid":   "学生是个约 12 岁的中国孩子，刚过剑桥 PET（B1 水平），英语看得懂、听不太懂，说得少，可能有点害羞。",
    "adult": "学生是一位大人，英语阅读不错、听力和口语弱（约 B1 水平），想练开口。",
}


# ---------- 出题：从 lesson.json 拼陪练的系统提示 ----------

SKIP_WORDS = {"phrasal", "podcast", "verb", "noun"}   # 生词表里的「词」其实不是内容词


def _key_words(glossary: dict, limit: int = 8) -> list[str]:
    hard = [w for w, v in glossary.items() if isinstance(v, dict) and v.get("hard")]
    hard = [w for w in hard if len(w) >= 4 and w.lower() not in SKIP_WORDS]
    hard.sort(key=lambda w: (-len(w), w))             # 长的更可能是值得聊的内容词
    return hard[:limit]


def _quote_sentences(lesson: dict, limit: int = 3) -> list[str]:
    """挑三句短的正文原话给陪练当锚点（能引用、能就此提问）。"""
    body_start = lesson.get("bodyStart") or 1
    candidates = [s for s in lesson.get("sentences", [])
                  if s.get("id", 0) >= body_start and len(s.get("text", "")) <= 70]
    if not candidates:
        return []
    step = max(1, len(candidates) // limit)
    picked = candidates[::step][:limit]
    return [f"- {s['text']}（{s.get('zh', '')}）" for s in picked]


def build_prompt(lesson_name: str, profile: str) -> dict:
    path = ROOT / "lessons" / lesson_name / "lesson.json"
    lesson = json.loads(path.read_text(encoding="utf-8"))
    sections = "；".join(f"第{i}段 {s['title']}" for i, s in enumerate(lesson.get("sections", []), 1))
    words = _key_words(lesson.get("glossary", {}))
    persona = ("语气活泼友善，像个耐心的大姐姐" if profile == "kid" else "语气平等自然，像朋友聊天")
    instructions = f"""你叫 Emma，是一位耐心、友善的英语口语陪练。你正在陪一位中国学生练口语，
学生刚听完一集英语播客，你们围绕这一集聊天。

学生情况：{PROFILES.get(profile, PROFILES['kid'])}
{persona}。这一集的播客是《{lesson.get('source', '')}》，标题《{lesson.get('title', '')}》，分四段：{sections}。

聊天的推进（自然一点，别像走流程）：
1. 开场：简短打招呼，请学生用两三句英语说说这一集大概讲了什么。
2. 就其中一两处追问细节，再看学生想聊哪段。
3. 把话题引到学生自己的生活（他的习惯、家里人的习惯、看法）。
4. 最后请学生用今天听到的一两个词说一句话，你给一句具体的肯定收尾。

必须守的规矩：
- 只说英语。语速放慢，句子短（一般不超过 10 个词），用词不超初中水平；一次只问一个问题。
- 话题始终围绕这一集和学生的生活，不跑题闲聊。
- 学生说错了不纠正、不评分：用正确的说法自然地接下去就好。
- 学生卡住、或用中文问某个词怎么说，先把那个词简单给出来，再鼓励他把话说完。
- 你少说、多说让学生说：多问、多听、多鼓励。
- 学生明显听不懂时，把话换得更短更简单再问一遍。

希望学生用起来的词（找机会自然引导，别硬塞）：{", ".join(words) if words else "（无）"}

这一集的几句原话（可以引用或就此提问）：
{chr(10).join(_quote_sentences(lesson)) or "（无）"}"""
    return {"instructions": instructions.strip(), "title": lesson.get("title", ""),
            "source": lesson.get("source", ""), "words": words}


# ---------- 8770：静态页和两个只读接口 ----------

class HttpHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args) -> None:  # noqa: A002
        pass

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self._file(ROOT / "web" / "speak-lab.html", "text/html; charset=utf-8")
            return
        if url.path == "/api/lessons":
            lessons = []
            for lesson_file in sorted((ROOT / "lessons").glob("*/lesson.json")):
                try:
                    d = json.loads(lesson_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                lessons.append({"lesson": lesson_file.parent.name, "title": d.get("title", ""),
                                "source": d.get("source", "")})
            self._json(200, {"lessons": lessons})
            return
        if url.path == "/api/prompt":
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            name, profile = q.get("lesson", ""), q.get("profile", "kid")
            if len(name) > LESSON_NAME_MAXLEN or not (ROOT / "lessons" / name / "lesson.json").exists():
                self._json(404, {"error": "没有这一课"})
                return
            if profile not in PROFILES:
                profile = "kid"
            self._json(200, build_prompt(name, profile))
            return
        if url.path.startswith("/fonts/"):
            font = Path(url.path).name                       # 只取文件名，防借路径乱读
            self._file(ROOT / "web" / "fonts" / font, "font/woff2")
            return
        self._json(404, {"error": "没有这个地址"})

    def _file(self, path: Path, ctype: str) -> None:
        try:
            raw = path.read_bytes()
        except OSError:
            self._json(404, {"error": "文件没了"})
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, code: int, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class HttpServer(ThreadingHTTPServer):
    allow_reuse_address = sys.platform != "win32"   # Windows 上独占端口（docs/lessons.md 2026-09-24）


# ---------- 上游地址和握手错误的翻译 ----------

def _workspace() -> str | None:
    try:
        return keys.read_key("qwen-workspace")
    except KeyError:
        return None


def upstream_urls(model_id: str) -> list[str]:
    """候选地址按序试：有业务空间就先试新的，旧地址兜底。"""
    urls = []
    ws = _workspace()
    if ws:
        urls.append(WORKSPACE_WS.format(workspace=ws, model_id=model_id))
    urls.append(LEGACY_WS.format(model_id=model_id))
    return urls


def _handshake_error(status: int) -> str:
    if status in (401, 403):
        return "百炼没认这把钥匙：看看控制台里模型开通了没有、钥匙对不对"
    if status == 404:
        return "接入地址或模型名不对：看看 api-keys.txt 里 #qwen-workspace 段写的业务空间 id"
    if status == 429:
        return "百炼说太挤了，稍后再试"
    return f"百炼拒绝了连接（{status}），去控制台看看这个模型"


# ---------- 8771：网页 ⇄ 百炼 的桥 ----------

from websockets.asyncio.client import connect  # noqa: E402
from websockets.asyncio.server import serve    # noqa: E402
from websockets.exceptions import ConnectionClosed, InvalidStatus  # noqa: E402


async def _pump(downstream, upstream, counter: dict, direction: str) -> None:
    """单方向原样转发文本帧；count 记字节，给会话结束的账单参考。"""
    if direction == "up":
        src, dst = downstream, upstream
    else:
        src, dst = upstream, downstream
    async for msg in src:
        if isinstance(msg, str):
            counter[direction] += len(msg)
            await dst.send(msg)


async def bridge_session(browser, model_key: str, lesson: str) -> None:
    model = MODELS[model_key]
    counter = {"up": 0, "down": 0}
    started = time.monotonic()
    label = f"[桥] {model_key} {lesson}"
    try:
        if model_key == "mock":
            print(f"{label} mock 开始")
            await mock_session(browser)
            return
        key = keys.read_key("qwen")
        upstream = None
        used_url = ""
        last_error = "没试任何地址"
        for url in upstream_urls(model["id"]):
            try:
                upstream = await connect(url, additional_headers={"Authorization": f"Bearer {key}"},
                                         open_timeout=15, ping_interval=20)
                used_url = url
                break
            except InvalidStatus as e:
                last_error = _handshake_error(e.response.status_code)
            except OSError:
                last_error = "连不上百炼，看看网络"
        if upstream is None:
            await browser.send(json.dumps({"type": "lab.error", "where": "connect", "message": last_error}))
            print(f"{label} 没连上：{last_error}")
            return
        print(f"{label} 已连上游 {urlparse(used_url).hostname}")
        try:
            async with asyncio.timeout(MAX_SESSION_SECONDS):
                done, pending = await asyncio.wait(
                    {asyncio.create_task(_pump(browser, upstream, counter, "up")),
                     asyncio.create_task(_pump(upstream, browser, counter, "down"))},
                    return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
        except (TimeoutError, asyncio.CancelledError):
            pass                                        # 到 11 分钟硬上限，收线
        finally:
            await upstream.close()
    except ConnectionClosed:
        pass                                            # 网页先关了，正常路
    except Exception as e:                              # 只记种类，不吐详情（红线）
        print(f"{label} 中断：{type(e).__name__}")
    finally:
        seconds = time.monotonic() - started
        print(f"{label} 结束 {seconds:.0f} 秒，上行 {counter['up'] / 1e6:.1f}MB、下行 {counter['down'] / 1e6:.1f}MB")


async def ws_entry(connection) -> None:
    q = {k: v[0] for k, v in parse_qs(urlparse(connection.request.path).query).items()}
    model_key, lesson = q.get("model", ""), q.get("lesson", "")
    if model_key not in MODELS or not lesson or len(lesson) > LESSON_NAME_MAXLEN:
        await connection.send(json.dumps({"type": "lab.error", "where": "params", "message": "参数不对"}))
        await connection.close()
        return
    await bridge_session(connection, model_key, lesson)


# ---------- mock：把事件链演一遍，不连百炼 ----------

async def mock_session(browser) -> None:
    import numpy as np                                  # 算正弦波（pywork 里有）

    await browser.send(json.dumps({"type": "session.created", "session": {}}))
    appended = 0
    reply_index = 0
    replies = [
        ("Hi! I am Emma. What was the podcast about?", "你好呀！我是 Emma。刚听的这集播客讲了什么？"),
        ("Interesting! Do you drink coffee at home?", "有意思！你在家喝咖啡吗？"),
        ("Great talking with you. See you next time!", "跟你聊得很开心，下次见！"),
    ]
    async for msg in browser:
        try:
            event = json.loads(msg)
        except Exception:
            continue
        etype = event.get("type", "")
        if etype == "session.update":
            await browser.send(json.dumps({"type": "session.updated", "session": event.get("session", {})}))
        elif etype == "input_audio_buffer.append":
            appended += len(event.get("audio", ""))
            if appended >= 80_000:                      # 约 2.5 秒说话量，触发一轮「你说完→它回话」
                appended = 0
                reply_en, reply_zh = replies[min(reply_index, len(replies) - 1)]
                reply_index += 1
                await browser.send(json.dumps({"type": "input_audio_buffer.speech_started"}))
                await asyncio.sleep(0.3)
                await browser.send(json.dumps({"type": "input_audio_buffer.committed"}))
                await browser.send(json.dumps({"type": "conversation.item.input_audio_transcription.completed",
                                               "transcript": "(mock: you said something)"}))
                await browser.send(json.dumps({"type": "response.created", "response": {}}))
                for word in reply_en.split(" "):
                    await browser.send(json.dumps({"type": "response.audio_transcript.delta", "delta": word + " "}))
                    await asyncio.sleep(0.04)
                await browser.send(json.dumps({"type": "response.audio_transcript.done",
                                               "transcript": reply_en + " " + reply_zh}))
                pcm = np.sin(2 * math.pi * 330 * np.arange(24000) / 24000)   # 1 秒 330Hz 正弦
                wave_bytes = (pcm * 12000).astype("<i2").tobytes()
                for i in range(0, len(wave_bytes), 2400):
                    await browser.send(json.dumps({"type": "response.audio.delta",
                                                   "delta": base64.b64encode(wave_bytes[i:i + 2400]).decode()}))
                    await asyncio.sleep(0.05)
                await browser.send(json.dumps({"type": "response.audio.done"}))
                await browser.send(json.dumps({"type": "response.done", "response": {}}))


# ---------- --selftest：连真模型放一段课程音频，看回话出不出得来 ----------

def _selftest_candidates(model_key: str, voice: str) -> list[dict]:
    """会话配置按模型出牌（3.8 认 semantic_vad；语音专线只认 server_vad/smart_turn）。
    每套独立试：谈成配置 → 放音频 → 等它开口，回话了才算这套能用。"""
    base = {
        "modalities": ["text", "audio"],
        "instructions": "This is a connectivity test. When you hear speech, reply with one short friendly English sentence.",
        "voice": voice,
        "input_audio_format": "pcm16", "output_audio_format": "pcm24",
        "input_audio_transcription": {"model": "qwen3-asr-flash-realtime"},
    }
    if model_key == "omni38":
        return [
            {**base, "turn_detection": {"type": "semantic_vad", "silence_duration_ms": 700},
             "audio": {"input": {"format": {"type": "pcm", "sample_rate": 16000, "sample_format": "s16le",
                                            "channels": 1, "packing": "interleaved", "channel_layout": "mono"}},
                       "output": {"format": {"type": "pcm", "sample_rate": 24000}, "voice": voice}}},
            {**base, "turn_detection": {"type": "server_vad", "silence_duration_ms": 700}},
        ]
    return [
        {**base, "turn_detection": {"type": "server_vad", "silence_duration_ms": 700}},   # 实测：这条能正常接话
        {**base, "turn_detection": {"type": "smart_turn"}},        # 实测 smart_turn 会把推流当环境音只转写不接话
    ]


async def selftest(model_key: str) -> int:
    assert model_key in MODELS and model_key != "mock", "omni38 或 audio31"
    model = MODELS[model_key]
    key = keys.read_key("qwen")
    upstream = None
    used_url = ""
    for url in upstream_urls(model["id"]):
        try:
            upstream = await connect(url, additional_headers={"Authorization": f"Bearer {key}"},
                                     open_timeout=15)
            used_url = url
            break
        except InvalidStatus as e:
            print(f"  地址没连上（{e.response.status_code}），换下一个")
    if upstream is None:
        print("  两个地址都没连上：看上面状态码，对照控制台查开通和钥匙")
        return 1
    await upstream.close()
    print(f"  握手成功：{urlparse(used_url).hostname}")

    # 放正文开头 6 秒（bodyStart 那句起）当「用户说话」，后面补 2 秒静音好让 VAD 断句
    lesson = json.loads((ROOT / "lessons" / "260821" / "lesson.json").read_text(encoding="utf-8"))
    start = float(lesson.get("bodyStart") or 10)
    with wave.open(str(ROOT / "lessons" / "260821" / "audio_16k.wav"), "rb") as w:
        w.setpos(int(start * w.getframerate()))
        frames = w.readframes(6 * w.getframerate())
    frames += b"\x00\x00" * 16000 * 2

    async def attempt(cfg: dict) -> dict:
        st = {"seen": [], "errors": [], "configured": False, "committed_at": None,
              "first_audio_at": None, "user": "", "ambient": "", "reply": ""}
        upstream = await connect(used_url, additional_headers={"Authorization": f"Bearer {key}"}, open_timeout=15)

        async def pump() -> None:
            async for msg in upstream:
                event = json.loads(msg)
                etype = event.get("type", "")
                if etype not in st["seen"]:
                    st["seen"].append(etype)
                if etype == "session.updated":
                    st["configured"] = True
                elif etype == "error":
                    st["errors"].append(json.dumps(event.get("error", {}), ensure_ascii=False)[:200])
                elif etype == "input_audio_buffer.committed":
                    st["committed_at"] = time.monotonic()
                elif etype == "response.audio.delta" and st["first_audio_at"] is None:
                    st["first_audio_at"] = time.monotonic()
                elif etype == "conversation.item.input_audio_transcription.completed":
                    st["user"] = event.get("transcript", "")
                elif etype == "conversation.item.ambient_audio_transcription.completed":
                    st["ambient"] = event.get("transcript", "")
                elif etype == "response.audio_transcript.delta":
                    st["reply"] += event.get("delta", "")
                elif etype == "response.done":
                    return

        pump_task = asyncio.create_task(pump())
        try:
            await upstream.send(json.dumps({"type": "session.update", "session": cfg}))
            deadline = time.monotonic() + 8
            while not st["configured"] and not st["errors"] and time.monotonic() < deadline:
                await asyncio.sleep(0.2)
            if not st["configured"]:
                return st                                   # 配置被顶回来，外层换下一套
            for i in range(0, len(frames), 3200):           # 100 毫秒一块地放
                await upstream.send(json.dumps({"type": "input_audio_buffer.append",
                                                "audio": base64.b64encode(frames[i:i + 3200]).decode()}))
                await asyncio.sleep(0.08)
            try:
                await asyncio.wait_for(pump_task, 18)       # 等它说完这一轮
            except TimeoutError:
                pass
        finally:
            pump_task.cancel()
            await upstream.close()
        return st

    candidates = _selftest_candidates(model_key, model["voice"])
    for idx, cfg in enumerate(candidates):
        turn_type = (cfg.get("turn_detection") or {}).get("type", "?")
        print(f"  —— 第 {idx + 1} 套（turn_detection={turn_type}）")
        st = await attempt(cfg)
        if st["errors"]:
            print("     模型报错：" + " ｜ ".join(st["errors"]))
        if st["user"]:
            print(f"     听到的用户说话：{st['user'][:110]}")
        if st["ambient"]:
            print(f"     （当成环境音转写了：{st['ambient'][:80]}）")
        if st["reply"]:
            print(f"     它回的话：{st['reply'][:110]}")
        if st["committed_at"] and st["first_audio_at"]:
            print(f"     说完到出声：{st['first_audio_at'] - st['committed_at']:.2f} 秒")
        if st["reply"]:
            print(f"  结论：通过（用第 {idx + 1} 套配置；事件类型：{'、'.join(st['seen'])}）")
            return 0
        print(f"     没回话。事件：{'、'.join(st['seen']) or '（一个都没有）'}")
    print("  结论：几套配置都没聊通——把上面的输出拿给 claude 看")
    return 1


# ---------- 起服务 ----------

def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        sys.exit(asyncio.run(selftest(sys.argv[2])))

    async def ws_serve() -> None:
        async with serve(ws_entry, "127.0.0.1", WS_PORT):
            await asyncio.Future()                     # 服务到关窗口为止

    httpd = HttpServer(("127.0.0.1", HTTP_PORT), HttpHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"口语实验页：http://localhost:{HTTP_PORT}/　（WS 桥在 {WS_PORT}；关掉这个窗口就停止）")
    if "--open" in sys.argv:
        webbrowser.open(f"http://localhost:{HTTP_PORT}/")
    try:
        asyncio.run(ws_serve())
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    main()
