"""对外模式的自动检查（SPEC-009 v7）：起真的服务、发真的 HTTP 请求。

查什么：访客免登录——页面、公共课、点词接口都开；上传/备课/删材料仍要会话；账号里的课
匿名永远碰不到（红线）；注册要邀请码、注册即登录；登录发会话 cookie；noindex；限流；
换版本接口对外关闭。

跑法：<pywork python> tests/test_hosted_server.py   （约 2 秒，不连网；
账号数据和公共课库写在临时目录，跑完就删。）
"""

import http.client
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import serve as serve_mod  # noqa: E402

failures: list[str] = []
passes: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passes if ok else failures).append(name)
    print(f"  {'通过' if ok else '未通过'}　{name}" + (f"　{detail}" if detail else ""))


def request(conn, method, path, body=None, cookie=None):
    headers = {}
    if body is not None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    else:
        raw = b""
    if cookie:
        headers["Cookie"] = cookie
    conn.request(method, path, body=raw, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    return resp, data


def fake_lesson(root: Path, name: str, title: str) -> None:
    """往 root/<name>/ 写一节最小可用的课（lesson.json＋假音频），root 是 shared/ 或账号的 lessons/。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "lesson.json").write_text(json.dumps({
        "lesson": name, "title": title, "source": "BBC · Real Easy English", "audio": "audio.m4a",
        "sentences": [{"id": 1, "text": "Hello.", "start": 0.0, "end": 1.5}],
        "sections": [],
    }, ensure_ascii=False), encoding="utf-8")
    (d / "audio.m4a").write_bytes(b"FAKE-AUDIO-BYTES" * 64)


tmp = Path(tempfile.mkdtemp(prefix="lm-hosted-"))
data = tmp / "data"
fake_lesson(data / "shared" / "lessons", "DAY1", "Coffee")   # 公共课库（R14）：访客听的就是它
server = serve_mod.make_server(
    port=0,
    hosted_config={"invite": "测试邀请码", "data_dir": data, "secure_cookie": False},
)
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_address[1]

try:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)

    # 匿名访客（v7）：直接进、直接听公共课
    resp, _ = request(conn, "GET", "/")
    check("匿名开根路径 → 直接去播放器", resp.status == 303 and resp.getheader("Location") == "/web/")
    resp, data_ = request(conn, "GET", "/web/index.html")
    check("匿名开页面放行", resp.status == 200)
    check("匿名响应也带 noindex", resp.getheader("X-Robots-Tag") == "noindex")
    resp, data_ = request(conn, "GET", "/login")
    check("登录页打得开（给已有账号的人）", resp.status == 200 and "注册".encode() in data_)
    resp, data_ = request(conn, "GET", "/api/library")
    lib = json.loads(data_)
    check("匿名资料库：user 为空、只有公共课、没有材料",
          lib.get("user") is None and lib.get("materials") == []
          and [x["lesson"] for x in lib.get("lessons", [])] == ["DAY1"], str(lib)[:80])
    resp, data_ = request(conn, "GET", "/lessons/DAY1/lesson.json")
    ok = resp.status == 200 and json.loads(data_).get("title") == "Coffee"
    check("匿名取公共课的 lesson.json", ok)
    conn.request("GET", "/lessons/DAY1/audio.m4a", headers={"Range": "bytes=10-20"})
    resp = conn.getresponse()
    resp.read()
    check("匿名拖动公共课音频（Range 206）", resp.status == 206)
    resp, _ = request(conn, "GET", "/lessons/NOPE/lesson.json")
    check("没有的课 404", resp.status == 404)
    # 网站根下的密钥和配置（2026-10-28 上线前堵的洞）：GET/HEAD、匿名/登录一律 404，只查状态码不看内容
    resp, _ = request(conn, "GET", "/api-keys.txt")
    check("匿名 GET /api-keys.txt → 404", resp.status == 404)
    resp, _ = request(conn, "GET", "/server-config.json")
    check("匿名 GET /server-config.json → 404", resp.status == 404)
    conn.request("HEAD", "/api-keys.txt")
    resp = conn.getresponse()
    resp.read()
    check("匿名 HEAD /api-keys.txt → 404", resp.status == 404)
    resp, data_ = request(conn, "POST", "/api/explain", body={"lesson": "NOPE", "sentence": 0, "word": 0})
    check("匿名点词放行（不存在的课报 404 而不是 401）", resp.status == 404)
    resp, data_ = request(conn, "POST", "/api/prep", body={"id": "x"})
    check("匿名备课 → 401", resp.status == 401)

    # 注册：错邀请码不行，对了就发会话
    resp, data_ = request(conn, "POST", "/api/register",
                          body={"email": "parent@example.com", "password": "passwd123", "invite": "错的"})
    check("错邀请码注册被拒", resp.status == 400 and "邀请码" in json.loads(data_)["error"])
    resp, data_ = request(conn, "POST", "/api/register",
                          body={"email": "parent@example.com", "password": "passwd123", "invite": "测试邀请码"})
    set_cookie = resp.getheader("Set-Cookie") or ""
    ok_reg = resp.status == 200 and "lm_session=" in set_cookie and "HttpOnly" in set_cookie
    check("对邀请码注册即登录（发会话 cookie）", ok_reg, set_cookie[:60])
    cookie = set_cookie.split(";")[0]

    # 账号里放一节自己的课，看指路和隔离
    own_lessons = Path(server.accounts.dir) / server.accounts.account_id("parent@example.com") / "lessons"
    fake_lesson(own_lessons, "MINE", "My Upload")
    resp, data_ = request(conn, "GET", "/api/library", cookie=cookie)
    lib = json.loads(data_)
    names = [x["lesson"] for x in lib.get("lessons", [])]
    check("登录后资料库：user 是邮箱、自己的课和公共课都在",
          lib.get("user") == "parent@example.com" and set(names) == {"MINE", "DAY1"}, str(names))
    resp, data_ = request(conn, "GET", "/lessons/MINE/lesson.json", cookie=cookie)
    check("登录取自己的课", resp.status == 200 and json.loads(data_).get("title") == "My Upload")
    resp, _ = request(conn, "GET", "/api-keys.txt", cookie=cookie)
    check("登录后 GET /api-keys.txt 也 → 404", resp.status == 404)
    resp, data_ = request(conn, "GET", "/lessons/DAY1/lesson.json", cookie=cookie)
    check("登录也能取公共课（自己没有的落公共库）", resp.status == 200)
    resp, _ = request(conn, "GET", "/lessons/MINE/lesson.json")
    check("匿名取账号里的课 → 404（红线：各家材料不外传）", resp.status == 404)

    # 换版本机制对外关闭
    resp, data_ = request(conn, "GET", "/api/version", cookie=cookie)
    v = json.loads(data_)
    check("对外模式 version 报 hosted 无更新", v.get("copy") == "hosted" and not v.get("update", {}).get("waiting"))
    resp, data_ = request(conn, "POST", "/api/update", body={}, cookie=cookie)
    check("对外模式没有「更新」接口", resp.status == 404)

    # 登出：会话作废——看不了账号里的课、资料库回到匿名形态
    resp, data_ = request(conn, "POST", "/api/logout", body={}, cookie=cookie)
    check("登出成功", resp.status == 200)
    resp, _ = request(conn, "GET", "/lessons/MINE/lesson.json", cookie=cookie)
    check("登出后账号里的课看不了", resp.status == 404)
    resp, data_ = request(conn, "GET", "/api/library", cookie=cookie)
    check("登出后资料库回到匿名（user 为空、只剩公共课）", json.loads(data_).get("user") is None)

    # 重新登录（同一账号），限流之前先拿到新会话
    resp, data_ = request(conn, "POST", "/api/login",
                          body={"email": "parent@example.com", "password": "passwd123"})
    cookie2 = (resp.getheader("Set-Cookie") or "").split(";")[0]
    check("登录发新会话", resp.status == 200 and cookie2.startswith("lm_session="))

    # 密码错：人话报错（放在限流打满之前，免得被 429 挡住）
    resp, data_ = request(conn, "POST", "/api/login",
                          body={"email": "parent@example.com", "password": "wrongwrong"})
    check("密码错报人话", resp.status == 400 and "邮箱或密码" in json.loads(data_)["error"])

    # 匿名上传被挡（handler 会关连接，放在限流打满前最后一条）
    conn.request("POST", "/api/upload?filename=x.mp3", body=b"xx",
                 headers={"Content-Type": "application/octet-stream"})
    resp = conn.getresponse()
    resp.read()
    check("匿名上传 → 401", resp.status == 401)

    # 限流：错邀请码注册不锁账号，连打超过限额应见 429
    saw_429 = False
    for i in range(40):
        resp, data_ = request(conn, "POST", "/api/register",
                              body={"email": f"x{i}@example.com", "password": "passwd123", "invite": "再错的"})
        if resp.status == 429:
            saw_429 = True
            break
    check("连打超限见到 429", saw_429)
finally:
    server.shutdown()
    server.server_close()
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n通过 {len(passes)} 项，未通过 {len(failures)} 项")
sys.exit(1 if failures else 0)
