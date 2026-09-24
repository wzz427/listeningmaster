"""本地网页服务，给播放器用。

为什么不用 python -m http.server：它不支持 Range 请求（从文件中间取一段）。
浏览器要跳到第 25 秒，必须能只取那一段；拿不到就跳不动，表现是「点下一句还是只播第一句」。
见 docs/lessons.md 2026-09-12 那条。

还管两个接口：孩子点词时现查讲解、现读朗读（pipeline/explain.py，决策 D29）。
密钥只在这个本地服务里用，网页拿不到；以后上服务器，放到网关上。

还管换版本（SPEC-008）：/api/version 告诉页面服务是哪一版、有没有钉着一版等 owner 点「更新」；
/api/update 是那颗「更新」：服务以退出码 7 停下，启动它的循环（pipeline/stable_copy.py run）换版本再起回来。

独占端口：Python 自带的 HTTPServer 会打开「地址可复用」，在 Windows 上这等于允许第二个服务同时占同一个端口，
不报错，请求随机分给新旧两个（2026-09-24 实测，docs/lessons.md）。所以这里关掉它。

用法：<pywork python> pipeline/serve.py [端口] [--open] [--managed]
  --open     起来以后打开浏览器（双击 start-player.bat 时第一次起用）
  --managed  由 stable_copy.py run 起的：有人负责换完版本把它拉起来，「更新」才能用
"""

import json
import os
import re
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHUNK = 64 * 1024
LESSON_NAME = re.compile(r"[0-9A-Za-z_-]+")   # 课名只许这些字符，防止借路径读到别的文件
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stable_copy  # noqa: E402


class Server(ThreadingHTTPServer):
    allow_reuse_address = sys.platform != "win32"   # 见文件开头「独占端口」
    version: str | None = None    # 起来时这份代码是哪个提交；换版本一定会重启，所以起来时记一次就对
    managed = False               # 有没有人负责换完版本把它拉起来
    exit_code = 0


class RangeHandler(SimpleHTTPRequestHandler):
    """支持 Range 的静态文件服务。"""

    def end_headers(self) -> None:
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")  # 改了代码刷新就生效
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] == "/api/version":
            self.send_json(200, self.version_state())
            return
        range_header = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not range_header or os.path.isdir(path):
            super().do_GET()
            return
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not match:
            super().do_GET()
            return
        try:
            handle = open(path, "rb")
        except OSError:
            self.send_error(404)
            return
        with handle:
            size = os.fstat(handle.fileno()).st_size
            first, last = match.groups()
            if first:
                start = int(first)
                end = int(last) if last else size - 1
            else:  # bytes=-500 表示最后 500 字节
                start = max(0, size - int(last))
                end = size - 1
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Type", self.guess_type(path))
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            handle.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = handle.read(min(CHUNK, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_POST(self) -> None:  # noqa: N802
        """点词时现查（pipeline/explain.py）：/api/explain 那一行，/api/more 展开的，/api/speak 现读。
        密钥只在这里用，不给网页。/api/update 是页面上那颗「更新」。"""
        if self.path == "/api/update":
            self.update()
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            lesson = str(body.get("lesson", ""))
            if not LESSON_NAME.fullmatch(lesson) or not (ROOT / "lessons" / lesson / "lesson.json").exists():
                self.send_json(404, {"error": "没有这一课"})
                return
            import explain
            if self.path == "/api/explain":
                self.send_json(200, explain.explain(lesson, int(body["sentence"]), int(body["word"])))
            elif self.path == "/api/more":
                self.send_json(200, explain.explain_more(lesson, int(body["sentence"]), int(body["word"])))
            elif self.path == "/api/speak":
                self.send_json(200, {"file": explain.speak(lesson, str(body.get("key", "")), str(body.get("text", "")))})
            else:
                self.send_json(404, {"error": "没有这个接口"})
        except Exception as e:  # 只回错误的种类，不回详情：详情里可能带着请求头（红线：密钥不进报错）
            self.send_json(500, {"error": type(e).__name__})

    def version_state(self) -> dict:
        """给页面：服务是哪一版（页面拿它判断自己旧没旧，不显示）、有没有一版等他点「更新」、上一次没换成的那句话。
        钉住的是哪个提交不给——给了就可能被印到屏幕上（SPEC-008 R9）。"""
        server: Server = self.server  # type: ignore[assignment]
        stable = stable_copy.is_stable(ROOT)
        invite = stable_copy.read_json(ROOT / stable_copy.INVITE) if stable else None
        waiting = bool(invite and server.managed and invite.get("commit") != server.version)
        last = stable_copy.read_json(ROOT / stable_copy.OUTCOME) if stable else None
        return {"version": server.version, "copy": "stable" if stable else "dev",
                "update": {"waiting": waiting, "what": (invite or {}).get("what", "") if waiting else ""},
                "failed": last.get("said") if last and not last.get("ok") else None}

    def update(self) -> None:
        """他点了「更新」：先回话，再停服务，退出码 7 告诉 stable_copy.py run 去换版本。
        没有要换的就拒绝：不许「成功地什么都不做」——服务停了、页面白了，他什么也没得到。"""
        if not self.version_state()["update"]["waiting"]:
            self.send_json(409, {"error": "现在没有要换的新版本。"})
            return
        server: Server = self.server  # type: ignore[assignment]
        server.exit_code = stable_copy.EXIT_UPDATE
        self.send_json(202, {"ok": True})
        threading.Thread(target=server.shutdown, daemon=True).start()  # 在别的线程里等 serve_forever 收摊

    def send_json(self, code: int, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # 安静点


def make_server(port: int = stable_copy.PORT, managed: bool = False) -> Server:
    server = Server(("127.0.0.1", port), partial(RangeHandler, directory=str(ROOT)))
    server.version = stable_copy.head(ROOT)
    server.managed = managed
    return server


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    port = int(args[0]) if args else stable_copy.PORT
    refusal = stable_copy.port_refusal(ROOT, port)
    if refusal:
        print(refusal)
        sys.exit(2)
    try:
        server = make_server(port, managed="--managed" in sys.argv)
    except OSError:
        print(f"{port} 端口被别的服务占着，多半是还开着一个播放器的黑窗口。把它关掉再起。")
        sys.exit(1)
    print(f"播放器地址：http://localhost:{port}/web/　（关掉这个窗口就停止）")
    if "--open" in sys.argv:
        webbrowser.open(stable_copy.page_url(port))
    server.serve_forever()
    server.server_close()
    sys.exit(server.exit_code)
