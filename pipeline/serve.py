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
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
CHUNK = 64 * 1024
LESSON_NAME = re.compile(r"[0-9A-Za-z_-]+")   # 课名只许这些字符，防止借路径读到别的文件
SESSION_COOKIE = "lm_session"
SESSION_MAX_AGE = 30 * 86400                  # 会话 30 天（SPEC-009 R1）
RATE_LIMIT = 30                               # 每 IP 每分钟 POST 次数（SPEC-009 R6）
PREP_STEPS = ["audio.py", "asr_probe.py", "align.py", "refine_bounds.py", "ear_bounds.py", "teach.py"]
PREP_TIMEOUT = 900                            # 单步最长 15 分钟（正常一步几十秒）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stable_copy  # noqa: E402


def _read_json(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path, obj) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)  # 原子替换，写一半断电不毁原文件


def _read_meta(mdir) -> dict:
    return _read_json(Path(mdir) / "meta.json")


class PrepFailed(Exception):
    """备课没成功：msg 是给人看的（不透内部细节），step 记哪一步（给运维）。"""

    def __init__(self, msg: str, step: str = ""):
        super().__init__(msg)
        self.step = step


def _prep_classify(step: str) -> str:
    if step == "audio.py":
        return "这份音频没读出来，换一份再试"
    if step == "asr_probe.py":
        return "语音识别没成功，稍后重试"
    return "备课没成功，稍后再试或换一份材料"


def _run_prep(server: "Server", email: str, mid: str) -> None:
    """备课任务（SPEC-009 R7、SPEC-002 流程）：材料搬进备课台（materials/<课>），
    跑六步（或配置里的自定义命令），成了把 lessons/<课> 搬进该账号、拆台；
    没成停在 failed，台子留着给运维看。串行队列，一次备一集。"""
    acc = server.accounts
    aid = acc.account_id(email)
    mdir = Path(acc.dir) / aid / "materials" / mid
    cfg = server.hosted_config
    materials_root = Path(cfg.get("materials_root") or ROOT / "materials")
    lessons_root = Path(cfg.get("lessons_root") or ROOT / "lessons")
    stage_m, stage_l = materials_root / mid, lessons_root / mid
    meta = _read_meta(mdir)
    meta.update({"state": "prepping", "prepping_since": int(time.time()), "error": None})
    _write_json(mdir / "meta.json", meta)
    try:
        shutil.rmtree(stage_m, ignore_errors=True)
        shutil.rmtree(stage_l, ignore_errors=True)
        stage_m.mkdir(parents=True, exist_ok=True)
        for f in sorted(mdir.glob("audio.*")):
            shutil.copy2(f, stage_m / f.name)
        if (mdir / "script.txt").exists():
            shutil.copy2(mdir / "script.txt", stage_m / "transcript.txt")  # 换成 pipeline 认的名字（SPEC-002）
        if (mdir / "script.pdf").exists():
            shutil.copy2(mdir / "script.pdf", stage_m / "transcript.pdf")  # PDF 讲稿 pipeline 本来就认
        if (mdir / "meta.json").exists():
            shutil.copy2(mdir / "meta.json", stage_m / "meta.json")        # 标题、来源：teach.py 从这读（R9）
        cmd = cfg.get("prep_command")
        if cmd:  # 自定义命令（测试用假命令，不烧识别和模型的钱）：参数＝课名、材料台、课台
            proc = subprocess.run([*cmd, mid, str(materials_root), str(lessons_root)],
                                  capture_output=True, timeout=PREP_TIMEOUT)
            if proc.returncode != 0:
                raise PrepFailed("备课没成功，稍后再试", step="自定义命令")
        else:  # 真六步（SPEC-002「流程」），一步一个程序、都带课名
            for name in PREP_STEPS:
                proc = subprocess.run([sys.executable, str(ROOT / "pipeline" / name), mid],
                                      capture_output=True, timeout=PREP_TIMEOUT)
                if proc.returncode != 0:
                    raise PrepFailed(_prep_classify(name), step=name)
        if not (stage_l / "lesson.json").exists():
            raise PrepFailed("备课没成功，稍后再试", step="生成课程文件")
        dest = Path(acc.dir) / aid / "lessons" / mid
        shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(stage_l), str(dest))
        shutil.rmtree(stage_m, ignore_errors=True)
        meta.update({"state": "done", "lesson": mid, "prepping_since": None})
    except PrepFailed as e:
        meta.update({"state": "failed", "error": str(e), "failed_step": e.step, "prepping_since": None})
    except Exception as e:  # 超时、断电这类：归类成一句人话，细节留在 failed_step
        meta.update({"state": "failed", "error": "备课没成功，稍后再试", "failed_step": type(e).__name__, "prepping_since": None})
    _write_json(mdir / "meta.json", meta)


def _prep_worker(server: "Server") -> None:
    while True:
        email, mid = server.prep_queue.get()
        try:
            _run_prep(server, email, mid)
        finally:
            server.prep_queue.task_done()


class Server(ThreadingHTTPServer):
    allow_reuse_address = sys.platform != "win32"   # 见文件开头「独占端口」
    version: str | None = None    # 起来时这份代码是哪个提交；换版本一定会重启，所以起来时记一次就对
    managed = False               # 有没有人负责换完版本把它拉起来
    exit_code = 0
    hosted = False                # 对外模式（SPEC-009）
    accounts = None               # 对外模式下的账号管理（pipeline/accounts.py 的实例）
    hosted_config: dict = {}      # 对外模式的配置（invite、data_dir、secure_cookie、max_upload_mb、prep_command、materials_root/lessons_root）
    prep_queue: "queue.Queue | None" = None   # 备课任务队列（对外模式起服务时建）
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

    def translate_path(self, path: str) -> str:
        """对外模式：/lessons/... 指到该账号自己的课目录（server-data/<账号id>/lessons/），
        各账号互不可见（SPEC-009 R5）；其余路径照旧。"""
        fs = super().translate_path(path)
        if self.server.hosted:
            email = self.session_email()
            if email and path.split("?")[0].split("/")[1:2] == ["lessons"]:
                try:
                    rel = Path(fs).resolve().relative_to(ROOT.resolve())
                except ValueError:
                    return fs
                return str(Path(self.server.accounts.dir) / self.server.accounts.account_id(email) / rel)
        return fs

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
            if path == "/api/library":
                self.send_json(200, self.library(email))
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
            post_path = self.path.split("?")[0]
            if post_path == "/api/prep":
                if not email:
                    self.send_json(401, {"error": "请先登录"})
                    return
                self.handle_prep(email)
                return
            if post_path == "/api/upload":
                if not email:
                    # 请求体（可能几十 MB）还没读就拒绝：必须关连接，不然残体顶坏下一个请求
                    self.send_json(401, {"error": "请先登录"}, close=True)
                    return
                self.handle_upload(email)
                return
            if post_path == "/api/material/delete":
                if not email:
                    self.send_json(401, {"error": "请先登录"})
                    return
                self.handle_material_delete(email)
                return
            if post_path == "/api/material/script":
                if not email:
                    self.send_json(401, {"error": "请先登录"})
                    return
                self.handle_material_script(email)
                return
            if not email:
                self.send_json(401, {"error": "请先登录"})
                return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            lesson = str(body.get("lesson", ""))
            lessons_root = None
            if self.server.hosted:  # 对外模式：课住该账号目录（SPEC-009 R5）
                accounts = self.server.accounts
                lessons_root = Path(accounts.dir) / accounts.account_id(email) / "lessons"
            lesson_json = (lessons_root or ROOT / "lessons") / lesson / "lesson.json"
            if not LESSON_NAME.fullmatch(lesson) or not lesson_json.exists():
                self.send_json(404, {"error": "没有这一课"})
                return
            import explain
            if self.path == "/api/explain":
                self.send_json(200, explain.explain(lesson, int(body["sentence"]), int(body["word"]), root=lessons_root))
            elif self.path == "/api/more":
                self.send_json(200, explain.explain_more(lesson, int(body["sentence"]), int(body["word"]), root=lessons_root))
            elif self.path == "/api/speak":
                self.send_json(200, {"file": explain.speak(lesson, str(body.get("key", "")), str(body.get("text", "")), root=lessons_root)})
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

    # ---------- 上传、资料库、删材料（SPEC-009 v3：上传只存材料，不触发备课） ----------

    def handle_upload(self, email: str) -> None:
        """音频按原始字节直接当请求体传（不走表单：省一道编码，进度条也好做）；
        文件名、标题、讲稿走 URL 参数。存进该账号目录，状态「未备课」。"""
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        # parse_qs 已经解过一次百分号编码，不能再 unquote：标题里带「%41」这类字样会被二次解码弄坏
        filename = q.get("filename", "")
        title = q.get("title", "").strip()
        source = q.get("source", "").strip()
        script = q.get("script", "").strip()
        length = int(self.headers.get("Content-Length") or 0)
        cap = int(self.server.hosted_config.get("max_upload_mb", 60)) * 1024 * 1024
        if length <= 0:
            self.send_json(400, {"error": "没收到文件"})
            return
        if length > cap:
            self.send_json(413, {"error": f"文件太大了，最大 {cap // 1024 // 1024}MB"})
            return
        ext = Path(filename).suffix.lower()
        if ext != ".mp3":  # 备课第 1 步只认 mp3（SPEC-002）；BBC 下载的就是 mp3
            self.send_json(400, {"error": "只收 mp3 音频"})
            return
        if not title:
            title = Path(filename).stem or "未命名材料"
        accounts = self.server.accounts
        mid = time.strftime("%y%m%d%H%M%S") + "-" + secrets.token_hex(3)
        mdir = Path(accounts.dir) / accounts.account_id(email) / "materials" / mid
        mdir.mkdir(parents=True, exist_ok=True)
        wrote, remaining = 0, length
        with open(mdir / f"audio{ext}", "wb") as f:
            while remaining > 0:
                chunk = self.rfile.read(min(CHUNK, remaining))
                if not chunk:
                    break
                f.write(chunk)
                wrote += len(chunk)
                remaining -= len(chunk)
        if wrote != length:
            shutil.rmtree(mdir, ignore_errors=True)
            self.send_json(400, {"error": "没传完整，再试一次"})
            return
        if script:
            (mdir / "script.txt").write_text(script, encoding="utf-8")
        meta = {"id": mid, "title": title, "source": source or None, "filename": filename, "size": wrote,
                "state": "new", "error": None, "lesson": None, "prepping_since": None,
                "uploaded_at": int(time.time())}
        _write_json(mdir / "meta.json", meta)
        self.send_json(200, {"ok": True, "material": meta})

    def handle_prep(self, email: str) -> None:
        """点「备课」（SPEC-009 R7）：状态先变 prepping 再进队列——重试立刻被 409 挡住，
        资料库也马上看得到「备课中」。真正的活在后台队列里串行跑。"""
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except Exception:
            body = {}
        mid = str(body.get("id", ""))
        if not LESSON_NAME.fullmatch(mid):
            self.send_json(400, {"error": "材料号不对"})
            return
        accounts = self.server.accounts
        mdir = Path(accounts.dir) / accounts.account_id(email) / "materials" / mid
        if not mdir.is_dir():
            self.send_json(404, {"error": "没有这个材料"})
            return
        meta = _read_meta(mdir)
        if meta.get("state") == "prepping":
            self.send_json(409, {"error": "正在备课，不用重复点"})
            return
        if meta.get("state") == "done":
            self.send_json(400, {"error": "这集已经备好了"})
            return
        meta.update({"state": "prepping", "prepping_since": int(time.time()), "error": None})
        _write_json(mdir / "meta.json", meta)
        self.server.prep_queue.put((email, mid))
        self.send_json(200, {"ok": True})

    def handle_material_delete(self, email: str) -> None:
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except Exception:
            body = {}
        mid = str(body.get("id", ""))
        if not LESSON_NAME.fullmatch(mid):
            self.send_json(400, {"error": "材料号不对"})
            return
        accounts = self.server.accounts
        mdir = Path(accounts.dir) / accounts.account_id(email) / "materials" / mid
        if not mdir.is_dir():
            self.send_json(404, {"error": "没有这个材料"})
            return
        if self._meta_state(mdir) == "prepping":
            self.send_json(409, {"error": "正在备课，等它跑完再删"})
            return
        shutil.rmtree(mdir)
        self.send_json(200, {"ok": True})

    def handle_material_script(self, email: str) -> None:
        """给材料补传／换讲稿文件（SPEC-009 v6：讲稿是传文件，不是粘贴；TXT、PDF、MD）。
        音频传上来没带讲稿的，在这里补上再备课；同一材料后传的顶掉先传的（md/txt 都存成 script.txt）。"""
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        mid, filename = q.get("id", ""), q.get("filename", "")
        ext = Path(filename).suffix.lower()
        if ext not in (".txt", ".pdf", ".md"):
            self.send_json(400, {"error": "讲稿只收 TXT、PDF、MD 文件"})
            return
        accounts = self.server.accounts
        mdir = Path(accounts.dir) / accounts.account_id(email) / "materials" / mid
        if not mdir.is_dir():
            self.send_json(404, {"error": "没有这个材料"})
            return
        if self._meta_state(mdir) == "prepping":
            self.send_json(409, {"error": "正在备课，等它跑完再换讲稿"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self.send_json(400, {"error": "没收到文件"})
            return
        if length > 2 * 1024 * 1024:
            self.send_json(413, {"error": "讲稿文件太大了，最大 2MB"})
            return
        data = self.rfile.read(length)
        for f in mdir.glob("script.*"):
            f.unlink()
        (mdir / ("script.pdf" if ext == ".pdf" else "script.txt")).write_bytes(data)
        self.send_json(200, {"ok": True})

    def library(self, email: str) -> dict:
        """侧边栏的数据（SPEC-009 R8）：该账号的材料（带状态）和课（带元数据）。
        材料按状态排：备课中最上、失败次之、未备课在后；已变课的不占材料区。"""
        accounts = self.server.accounts
        base = Path(accounts.dir) / accounts.account_id(email)
        order = {"prepping": 0, "failed": 1, "new": 2}
        materials = []
        mdir = base / "materials"
        if mdir.is_dir():
            for meta_file in sorted(mdir.glob("*/meta.json")):
                meta = _read_json(meta_file)
                if not meta or meta.get("state") == "done":
                    continue
                if meta.get("state") == "prepping" and meta.get("prepping_since"):
                    meta["prepping_for"] = int(time.time() - meta["prepping_since"])
                meta["has_script"] = any((meta_file.parent / f"script.{e}").exists() for e in ("txt", "pdf"))
                materials.append(meta)
        materials.sort(key=lambda m: (order.get(m.get("state"), 9), -(m.get("uploaded_at") or 0)))
        lessons = []
        ldir = base / "lessons"
        if ldir.is_dir():
            for lesson_file in sorted(ldir.glob("*/lesson.json")):
                try:
                    d = json.loads(lesson_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                sentences = d.get("sentences") or []
                lessons.append({
                    "lesson": lesson_file.parent.name,
                    "title": d.get("title") or lesson_file.parent.name,
                    "source": d.get("source") or "",
                    "sentences": len(sentences),
                    "duration": round(max((s.get("end") or 0) for s in sentences), 1) if sentences else 0,
                    "sections": len(d.get("sections") or []),
                })
        return {"materials": materials, "lessons": lessons}

    @staticmethod
    def _meta_state(mdir: Path) -> str:
        return _read_meta(mdir).get("state") or ""

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

    def send_json(self, code: int, data: dict, cookie: str | None = None, raw_cookie: str | None = None,
                  close: bool = False) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        if close:
            self.send_header("Connection", "close")
        if cookie:  # 登录成功发会话 cookie：30 天、HttpOnly、SameSite=Lax；HTTPS 后面加 Secure（SPEC-009 R1）
            parts = [f"{SESSION_COOKIE}={cookie}", "Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={SESSION_MAX_AGE}"]
            if self.server.secure_cookie:
                parts.append("Secure")
            self.send_header("Set-Cookie", "; ".join(parts))
        if raw_cookie:
            self.send_header("Set-Cookie", raw_cookie)
        self.end_headers()
        self.wfile.write(raw)
        if close:
            self.close_connection = True

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # 安静点


def make_server(port: int = stable_copy.PORT, managed: bool = False, hosted_config: dict | None = None) -> Server:
    """hosted_config：{"invite": 邀请码, "data_dir": 数据目录, "secure_cookie": bool, "bind": 绑哪个地址}——
    给了就起对外模式。bind 默认 127.0.0.1；Caddy 跑在 docker 容器里的机器上要写 "0.0.0.0"
    （容器经网桥 172.x.0.1 才够得着宿主机；对外仍靠轻量防火墙只放 80/443/22）。"""
    import accounts
    host = (hosted_config or {}).get("bind") or "127.0.0.1"
    server = Server((host, port), partial(RangeHandler, directory=str(ROOT)))
    server.version = stable_copy.head(ROOT)
    server.managed = managed
    if hosted_config:
        server.hosted = True
        server.hosted_config = hosted_config
        server.accounts = accounts.Accounts(hosted_config["data_dir"], invite_code=hosted_config["invite"])
        server.secure_cookie = bool(hosted_config.get("secure_cookie"))
        server.prep_queue = queue.Queue()
        threading.Thread(target=_prep_worker, args=(server,), daemon=True).start()
    return server


def load_hosted_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return {"invite": str(cfg["invite"]),
            "data_dir": path.parent / cfg.get("data_dir", "server-data"),
            "secure_cookie": bool(cfg.get("secure_cookie", False)),
            "port": int(cfg.get("port", 8790)),
            "bind": str(cfg.get("bind", "127.0.0.1"))}


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
