"""本地网页服务，给播放器用；--hosted 起对外模式（SPEC-009）。

为什么不用 python -m http.server：它不支持 Range 请求（从文件中间取一段）。
浏览器要跳到第 25 秒，必须能只取那一段；拿不到就跳不动，表现是「点下一句还是只播第一句」。
见 docs/lessons.md 2026-09-12 那条。

还管两个接口：孩子点词时现查讲解、现读朗读（pipeline/explain.py，决策 D29）。
密钥只在这个服务里用，网页拿不到；对外模式密钥住服务器（D29 定的方向）。

本地模式还管换版本（SPEC-008）：/api/version 告诉页面服务是哪一版、有没有钉着一版等 owner 点「更新」；
/api/update 是那颗「更新」：服务以退出码 7 停下，启动它的循环（pipeline/stable_copy.py run）换版本再起回来。

对外模式（--hosted，SPEC-009 v3）：
- 账号挡整个站：页面、音频、每个接口都先查会话 cookie，没有就到登录页（pipeline/accounts.py）；
- 注册（邮箱＋密码＋邀请码）/ 登录 / 登出；
- 所有响应带 X-Robots-Tag: noindex（不被搜索引擎收录）；
- POST 接口按 IP 限流（每分钟 30 次；经反代时取 X-Forwarded-For 的第一个）；
- 换版本机制整个关掉：/api/version 恒报 hosted、无「更新」，/api/update 404。

独占端口：Python 自带的 HTTPServer 会打开「地址可复用」，在 Windows 上这等于允许第二个服务同时占同一个端口，
不报错，请求随机分给新旧两个（2026-09-24 实测，docs/lessons.md）。所以 Windows 上关掉它；
Linux（对外模式部署）保持默认开，重启才不卡在 TIME_WAIT。

用法：<pywork python> pipeline/serve.py [端口] [--open] [--managed]
      <python> pipeline/serve.py --hosted        （读仓库根的 server-config.json：invite、port、data_dir、secure_cookie）
  --open     起来以后打开浏览器（双击 start-player.bat 时第一次起用）
  --managed  由 stable_copy.py run 起的：有人负责换完版本把它拉起来，「更新」才能用
"""

import http.cookies
import json
import os
import re
import sys
import threading
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHUNK = 64 * 1024
LESSON_NAME = re.compile(r"[0-9A-Za-z_-]+")   # 课名只许这些字符，防止借路径读到别的文件
SESSION_COOKIE = "lm_session"
SESSION_MAX_AGE = 30 * 86400                  # 会话 30 天（SPEC-009 R1）
RATE_LIMIT = 30                               # 每 IP 每分钟 POST 次数（SPEC-009 R6）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stable_copy  # noqa: E402


class Server(ThreadingHTTPServer):
    allow_reuse_address = sys.platform != "win32"   # 见文件开头「独占端口」
    version: str | None = None    # 起来时这份代码是哪个提交；换版本一定会重启，所以起来时记一次就对
    managed = False               # 有没有人负责换完版本把它拉起来
    exit_code = 0
    hosted = False                # 对外模式（SPEC-009）
    accounts = None               # 对外模式下的账号管理（pipeline/accounts.py 的实例）
    secure_cookie = False         # 对外模式在 HTTPS 后面时给 cookie 加 Secure
    _rl_lock = threading.Lock()
    _rl: dict[str, list] = {}     # ip -> [窗口起点, 已计次]

    def rate_ok(self, ip: str) -> bool:
        now = time.time()
        with self._rl_lock:
            window, count = self._rl.get(ip, [0.0, 0])
            if now - window >= 60:
                self._rl[ip] = [now, 1]
                return True
            count += 1
            self._rl[ip] = [window, count]
            return count <= RATE_LIMIT


class RangeHandler(SimpleHTTPRequestHandler):
    """支持 Range 的静态文件服务；对外模式多挡一层账号（SPEC-009）。"""

    def end_headers(self) -> None:
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")  # 改了代码刷新就生效
        if self.server.hosted:
            self.send_header("X-Robots-Tag", "noindex")  # 不被搜索引擎收录（SPEC-009 R3）
        super().end_headers()

    # ---------- 会话 ----------

    def session_email(self) -> str | None:
        """对外模式：会话 cookie -> 邮箱；无效或过期回 None。本地模式不需要。"""
        cookie = http.cookies.SimpleCookie()
        cookie.load(self.headers.get("Cookie") or "")
        morsel = cookie.get(SESSION_COOKIE)
        if not morsel:
            return None
        return self.server.accounts.email_of(morsel.value)

    def client_ip(self) -> str:
        """限流用的 IP：对外模式躲在反代后面，取 X-Forwarded-For 的第一个。"""
        if self.server.hosted:
            xff = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            if xff:
                return xff
        return self.client_address[0]

    # ---------- GET ----------

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/version":
            self.send_json(200, self.version_state())
            return
        if self.server.hosted:
            email = self.session_email()
            if not email:
                if path.startswith("/api/"):
                    self.send_json(401, {"error": "请先登录"})
                elif path in ("/", "/login"):
                    self.serve_file_bytes(ROOT / "web" / "login.html", "text/html; charset=utf-8")
                else:  # 页面、音频、一切：没有会话一律去登录页（SPEC-009 R1：直链也打不开）
                    self.send_response(303)
                    self.send_header("Location", "/login")
                    self.end_headers()
                return
            if path in ("/", "/login"):
                self.send_response(303)
                self.send_header("Location", "/web/")
                self.end_headers()
                return
        range_header = self.headers.get("Range")
        path_fs = self.translate_path(self.path)
        if not range_header or os.path.isdir(path_fs):
            super().do_GET()
            return
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not match:
            super().do_GET()
            return
        try:
            handle = open(path_fs, "rb")
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
            self.send_header("Content-Type", self.guess_type(path_fs))
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

    # ---------- POST ----------

    def do_POST(self) -> None:  # noqa: N802
        """对外模式：注册/登录/登出（pipeline/accounts.py）。
        两边都有：点词时现查（pipeline/explain.py）——/api/explain 那一行，/api/more 展开的，/api/speak 现读。
        密钥只在这里用，不给网页。/api/update 是本地模式页面上那颗「更新」。"""
        if self.path == "/api/update" and not self.server.hosted:
            self.update()
            return
        if self.server.hosted:
            if not self.server.rate_ok(self.client_ip()):
                self.send_json(429, {"error": "点得太快了，歇一分钟再试"})
                return
            email = self.session_email()
            if self.path in ("/api/register", "/api/login"):
                self.handle_auth()
                return
            if self.path == "/api/logout":
                self.handle_logout()
                return
            if self.path == "/api/update":
                self.send_json(404, {"error": "没有这个接口"})  # 对外模式没有换版本（SPEC-009 R4）
                return
            if not email:
                self.send_json(401, {"error": "请先登录"})
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

    # ---------- 对外模式的账号接口 ----------

    def handle_auth(self) -> None:
        import accounts
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            email, password, invite = str(body.get("email", "")), str(body.get("password", "")), str(body.get("invite", ""))
            if self.path == "/api/register":
                self.server.accounts.register(email, password, invite)
                token = self.server.accounts.login(email, password)  # 注册即登录（SPEC-009：注册即用）
                self.send_json(200, {"ok": True}, cookie=token)
            else:
                token = self.server.accounts.login(email, password)
                self.send_json(200, {"ok": True}, cookie=token)
        except accounts.AccountsError as e:  # 错误就是给人看的（accounts.py 只回人话）
            self.send_json(400, {"error": str(e)})
        except Exception as e:
            self.send_json(500, {"error": type(e).__name__})

    def handle_logout(self) -> None:
        cookie = http.cookies.SimpleCookie()
        cookie.load(self.headers.get("Cookie") or "")
        morsel = cookie.get(SESSION_COOKIE)
        if morsel:
            self.server.accounts.logout(morsel.value)
        expire = f"{SESSION_COOKIE}=; Path=/; Max-Age=0"
        self.send_json(200, {"ok": True}, raw_cookie=expire)

    # ---------- 换版本（本地模式，SPEC-008） ----------

    def version_state(self) -> dict:
        """给页面：服务是哪一版（页面拿它判断自己旧没旧，不显示）、有没有一版等他点「更新」、上一次没换成的那句话。
        钉住的是哪个提交不给——给了就可能被印到屏幕上（SPEC-008 R9）。对外模式恒报 hosted、无更新（R4）。"""
        server: Server = self.server  # type: ignore[assignment]
        if server.hosted:
            return {"version": server.version, "copy": "hosted",
                    "update": {"waiting": False, "what": ""}, "failed": None}
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

    # ---------- 应答的小工具 ----------

    def serve_file_bytes(self, path: Path, ctype: str) -> None:
        try:
            raw = path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, code: int, data: dict, cookie: str | None = None, raw_cookie: str | None = None) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        if cookie:  # 登录成功发会话 cookie：30 天、HttpOnly、SameSite=Lax；HTTPS 后面加 Secure（SPEC-009 R1）
            parts = [f"{SESSION_COOKIE}={cookie}", "Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={SESSION_MAX_AGE}"]
            if self.server.secure_cookie:
                parts.append("Secure")
            self.send_header("Set-Cookie", "; ".join(parts))
        if raw_cookie:
            self.send_header("Set-Cookie", raw_cookie)
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # 安静点


def make_server(port: int = stable_copy.PORT, managed: bool = False, hosted_config: dict | None = None) -> Server:
    """hosted_config：{"invite": 邀请码, "data_dir": 数据目录, "secure_cookie": bool}——给了就起对外模式。"""
    import accounts
    server = Server(("127.0.0.1", port), partial(RangeHandler, directory=str(ROOT)))
    server.version = stable_copy.head(ROOT)
    server.managed = managed
    if hosted_config:
        server.hosted = True
        server.accounts = accounts.Accounts(hosted_config["data_dir"], invite_code=hosted_config["invite"])
        server.secure_cookie = bool(hosted_config.get("secure_cookie"))
    return server


def load_hosted_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return {"invite": str(cfg["invite"]),
            "data_dir": path.parent / cfg.get("data_dir", "server-data"),
            "secure_cookie": bool(cfg.get("secure_cookie", False)),
            "port": int(cfg.get("port", 8790))}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    hosted = "--hosted" in sys.argv
    if hosted:
        hosted_config = load_hosted_config(ROOT / "server-config.json")
        port = hosted_config["port"]
    else:
        hosted_config = None
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        port = int(args[0]) if args else stable_copy.PORT
    refusal = stable_copy.port_refusal(ROOT, port)
    if refusal:
        print(refusal)
        sys.exit(2)
    try:
        server = make_server(port, managed="--managed" in sys.argv, hosted_config=hosted_config)
    except OSError:
        print(f"{port} 端口被别的服务占着，多半是还开着一个播放器的黑窗口。把它关掉再起。")
        sys.exit(1)
    if hosted:
        print(f"对外模式已起：http://127.0.0.1:{port}/login　（躲在反代后面用；关掉这个窗口就停止）")
    else:
        print(f"播放器地址：http://localhost:{port}/web/　（关掉这个窗口就停止）")
        if "--open" in sys.argv:
            webbrowser.open(stable_copy.page_url(port))
    server.serve_forever()
    server.server_close()
    sys.exit(server.exit_code)
