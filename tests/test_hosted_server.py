"""对外模式的自动检查（SPEC-009 v3）：起真的服务、发真的 HTTP 请求。

查什么：没会话什么都看不到（页面、接口）；注册要邀请码、注册即登录；
登录发会话 cookie，带着它才能拿东西；noindex；限流；换版本接口对外关闭。

跑法：<pywork python> tests/test_hosted_server.py   （约 2 秒，不连网；
账号数据写在临时目录，跑完就删。）
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


tmp = Path(tempfile.mkdtemp(prefix="lm-hosted-"))
server = serve_mod.make_server(
    port=0,
    hosted_config={"invite": "测试邀请码", "data_dir": tmp / "data", "secure_cookie": False},
)
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_address[1]

try:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)

    # 没会话：页面重定向去登录页，接口 401，音频直链也不给
    resp, _ = request(conn, "GET", "/web/index.html")
    check("没会话开页面 → 去登录页", resp.status == 303 and resp.getheader("Location") == "/login")
    resp, data = request(conn, "GET", "/login")
    check("登录页打得开", resp.status == 200 and "注册".encode() in data)
    check("登录页 noindex", resp.getheader("X-Robots-Tag") == "noindex")
    resp, data = request(conn, "GET", "/lessons/260821/audio.m4a")
    check("没会话开音频直链 → 去登录页", resp.status == 303 and resp.getheader("Location") == "/login")
    resp, data = request(conn, "POST", "/api/explain", body={"lesson": "260821", "sentence": 0, "word": 0})
    check("没会话调接口 → 401", resp.status == 401)

    # 注册：错邀请码不行，对了就发会话
    resp, data = request(conn, "POST", "/api/register",
                         body={"email": "parent@example.com", "password": "passwd123", "invite": "错的"})
    check("错邀请码注册被拒", resp.status == 400 and "邀请码" in json.loads(data)["error"])
    resp, data = request(conn, "POST", "/api/register",
                         body={"email": "parent@example.com", "password": "passwd123", "invite": "测试邀请码"})
    set_cookie = resp.getheader("Set-Cookie") or ""
    ok_reg = resp.status == 200 and "lm_session=" in set_cookie and "HttpOnly" in set_cookie
    check("对邀请码注册即登录（发会话 cookie）", ok_reg, set_cookie[:60])
    cookie = set_cookie.split(";")[0]

    # 带会话：页面放行，换版本机制关闭
    resp, data = request(conn, "GET", "/web/index.html", cookie=cookie)
    check("带会话开页面放行", resp.status == 200)
    resp, data = request(conn, "GET", "/api/version", cookie=cookie)
    v = json.loads(data)
    check("对外模式 version 报 hosted 无更新", v.get("copy") == "hosted" and not v.get("update", {}).get("waiting"))
    resp, data = request(conn, "POST", "/api/update", body={}, cookie=cookie)
    check("对外模式没有「更新」接口", resp.status == 404)

    # 登出：会话作废
    resp, data = request(conn, "POST", "/api/logout", body={}, cookie=cookie)
    check("登出成功", resp.status == 200)
    resp, _ = request(conn, "GET", "/web/index.html", cookie=cookie)
    check("登出后会话作废", resp.status == 303)

    # 重新登录（同一账号），限流之前先拿到新会话
    resp, data = request(conn, "POST", "/api/login",
                         body={"email": "parent@example.com", "password": "passwd123"})
    cookie2 = (resp.getheader("Set-Cookie") or "").split(";")[0]
    check("登录发新会话", resp.status == 200 and cookie2.startswith("lm_session="))

    # 密码错：人话报错（放在限流打满之前，免得被 429 挡住）
    resp, data = request(conn, "POST", "/api/login",
                         body={"email": "parent@example.com", "password": "wrongwrong"})
    check("密码错报人话", resp.status == 400 and "邮箱或密码" in json.loads(data)["error"])

    # 限流：错邀请码注册不锁账号，连打超过限额应见 429
    saw_429 = False
    for i in range(40):
        resp, data = request(conn, "POST", "/api/register",
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
