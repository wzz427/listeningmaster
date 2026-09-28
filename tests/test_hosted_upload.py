"""上传、资料库、删材料的自动检查（SPEC-009 v3：上传只存材料，不触发备课）。

跑法：<pywork python> tests/test_hosted_upload.py   （约 2 秒，不连网；
账号和材料写在临时目录里，跑完就删。音频用的是假字节——这层只管存和列，不验内容。）
"""

import http.client
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import serve as serve_mod  # noqa: E402

failures: list[str] = []
passes: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passes if ok else failures).append(name)
    print(f"  {'通过' if ok else '未通过'}　{name}" + (f"　{detail}" if detail else ""))


def post_json(conn, path, body, cookie=None):
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    conn.request("POST", path, body=raw, headers=headers)
    resp = conn.getresponse()
    return resp, resp.read()


def get(conn, path, cookie=None):
    headers = {"Cookie": cookie} if cookie else {}
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()
    return resp, resp.read()


tmp = Path(tempfile.mkdtemp(prefix="lm-upload-"))
server = serve_mod.make_server(
    port=0,
    hosted_config={"invite": "测试邀请码", "data_dir": tmp / "data", "secure_cookie": False},
)
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_address[1]

try:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)

    # 两个账号
    resp, data = post_json(conn, "/api/register", {"email": "a@example.com", "password": "passwd123", "invite": "测试邀请码"})
    cookie_a = (resp.getheader("Set-Cookie") or "").split(";")[0]
    resp, data = post_json(conn, "/api/register", {"email": "b@example.com", "password": "passwd123", "invite": "测试邀请码"})
    cookie_b = (resp.getheader("Set-Cookie") or "").split(";")[0]

    # 没登录不许传
    conn.request("POST", "/api/upload?filename=x.mp3", body=b"x" * 10, headers={})
    resp = conn.getresponse()
    resp.read()
    check("没会话上传被拒", resp.status == 401)

    # 类型不对
    conn.request("POST", "/api/upload?filename=" + quote("病毒.exe"), body=b"x" * 10, headers={"Cookie": cookie_a})
    resp = conn.getresponse()
    data = resp.read()
    check("非音频被拒", resp.status == 400 and "只收 mp3" in json.loads(data)["error"])

    # 正常上传两条：一条不带标题（用文件名），一条带标题、来源和讲稿
    audio1 = b"FAKE_MP3_BYTES_" * 64
    q1 = "/api/upload?filename=" + quote("cafe.mp3")
    conn.request("POST", q1, body=audio1, headers={"Cookie": cookie_a})
    resp = conn.getresponse()
    m1 = json.loads(resp.read())["material"]
    check("上传成功、默认标题用文件名", resp.status == 200 and m1["title"] == "cafe" and m1["state"] == "new")

    q2 = ("/api/upload?filename=" + quote("sleep.mp3") + "&title=" + quote("你睡得好吗")
          + "&source=" + quote("Real Easy English") + "&script=" + quote("Hello and welcome."))
    conn.request("POST", q2, body=b"FAKE2_" * 32, headers={"Cookie": cookie_a})
    resp = conn.getresponse()
    m2 = json.loads(resp.read())["material"]
    check("带标题、来源和讲稿上传成功", resp.status == 200 and m2["title"] == "你睡得好吗" and m2["source"] == "Real Easy English")

    # 资料库：A 有两条材料、零节课；B 什么都没有（隔离）
    resp, data = get(conn, "/api/library", cookie_a)
    lib_a = json.loads(data)
    check("A 的材料两条、课为零", len(lib_a["materials"]) == 2 and lib_a["lessons"] == [])
    check("材料状态都是未备课", all(m["state"] == "new" for m in lib_a["materials"]))
    resp, data = get(conn, "/api/library", cookie_b)
    check("B 的资料库是空的（隔离）", json.loads(data) == {"materials": [], "lessons": []})

    # 讲稿落了盘、音频字节原样
    base_a = Path(server.accounts.dir) / server.accounts.account_id("a@example.com")
    check("音频原样落盘", (base_a / "materials" / m1["id"] / "audio.mp3").read_bytes() == audio1)
    check("讲稿落盘", "Hello and welcome." in (base_a / "materials" / m2["id"] / "script.txt").read_text(encoding="utf-8"))

    # 课目录的隔离：A 名下放假的课，B 取不到
    lesson_dir = base_a / "lessons" / "26092801"
    lesson_dir.mkdir(parents=True)
    (lesson_dir / "lesson.json").write_text(json.dumps({
        "title": "假课", "source": "测试", "sections": [{"first": 0, "last": 1, "title": "一段"}],
        "sentences": [{"id": 0, "start": 0, "end": 3.5, "text": "Hi.", "zh": "嗨", "speaker": "测试"}],
    }), encoding="utf-8")
    (lesson_dir / "audio.m4a").write_bytes(b"FAKE_M4A")
    resp, data = get(conn, "/lessons/26092801/audio.m4a", cookie_a)
    check("A 能取自己账号下的课音频", resp.status == 200 and data == b"FAKE_M4A")
    resp, data = get(conn, "/lessons/26092801/audio.m4a", cookie_b)
    check("B 取不到 A 的课（隔离）", resp.status == 404)
    resp, data = get(conn, "/api/library", cookie_a)
    lesson_row = json.loads(data)["lessons"][0]
    check("资料库列出课的元数据", lesson_row["lesson"] == "26092801" and lesson_row["title"] == "假课"
          and lesson_row["sentences"] == 1 and lesson_row["duration"] == 3.5)

    # 删材料
    resp, data = post_json(conn, "/api/material/delete", {"id": m1["id"]}, cookie=cookie_a)
    check("删未备课的材料", resp.status == 200)
    resp, data = post_json(conn, "/api/material/delete", {"id": m1["id"]}, cookie=cookie_a)
    check("再删报没有", resp.status == 404)
    resp, data = get(conn, "/api/library", cookie_a)
    check("删完材料区剩一条", len(json.loads(data)["materials"]) == 1)

    # 超限：谎报一个超过上限的 Content-Length
    conn2 = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn2.request("POST", "/api/upload?filename=" + quote("big.mp3"), body=b"x" * 16,
                  headers={"Cookie": cookie_a, "Content-Length": str(61 * 1024 * 1024)})
    resp = conn2.getresponse()
    resp.read()
    check("超过 60MB 被拒", resp.status == 413)

    # 讲稿文件（SPEC-009 v6：传文件不是粘贴；TXT/MD 存 script.txt，PDF 存 script.pdf，后传的顶先传的）
    conn.request("POST", "/api/upload?filename=" + quote("talk.mp3"), body=b"FAKE3_" * 10,
                 headers={"Cookie": cookie_a})
    m3 = json.loads(conn.getresponse().read())["material"]["id"]
    _, data = get(conn, "/api/library", cookie_a)
    row3 = next(m for m in json.loads(data)["materials"] if m["id"] == m3)
    check("新材料的 has_script 是没有", row3["has_script"] is False)
    conn.request("POST", f"/api/material/script?id={m3}&filename=" + quote("讲稿.docx"), body=b"x",
                 headers={"Cookie": cookie_a})
    resp = conn.getresponse()
    body = resp.read()
    check("讲稿选错类型被拒（只收 TXT、PDF、MD）", resp.status == 400 and "TXT" in json.loads(body)["error"])
    conn.request("POST", f"/api/material/script?id={m3}&filename=" + quote("notes.md"),
                 body="Georgie: Hello again.".encode("utf-8"), headers={"Cookie": cookie_a})
    resp = conn.getresponse()
    resp.read()
    base_a3 = Path(server.accounts.dir) / server.accounts.account_id("a@example.com") / "materials" / m3
    check("MD 讲稿存成 script.txt", resp.status == 200
          and (base_a3 / "script.txt").read_text(encoding="utf-8") == "Georgie: Hello again.")
    conn.request("POST", f"/api/material/script?id={m3}&filename=" + quote("talk.pdf"),
                 body=b"%PDF-1.4 fake", headers={"Cookie": cookie_a})
    resp = conn.getresponse()
    resp.read()
    check("PDF 讲稿顶掉 txt（同名只留一份）", resp.status == 200 and (base_a3 / "script.pdf").exists()
          and not (base_a3 / "script.txt").exists())
    _, data = get(conn, "/api/library", cookie_a)
    row3 = next(m for m in json.loads(data)["materials"] if m["id"] == m3)
    check("补传后 has_script 变有", row3["has_script"] is True)
    conn.request("POST", f"/api/material/script?id={m3}&filename=" + quote("x.txt"), body=b"x",
                 headers={"Cookie": cookie_b})
    resp = conn.getresponse()
    resp.read()
    check("别的账号补不了你的讲稿（隔离）", resp.status == 404)
finally:
    server.shutdown()
    server.server_close()
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n通过 {len(passes)} 项，未通过 {len(failures)} 项")
sys.exit(1 if failures else 0)
