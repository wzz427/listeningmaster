"""备课任务的自动检查（SPEC-009 R7、SPEC-002 流程）。

用假备课命令（prep_command 注入）把状态机整条跑通：new → prepping → done / failed → 重试。
不连网、不烧识别和模型的钱；真六步在服务器上首次部署时用真材料验（SPEC-009 部署手册）。

跑法：<pywork python> tests/test_hosted_prep.py   （约 5 秒；账号、备课台全在临时目录，跑完就删）
"""

import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
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
    conn.request("GET", path, headers={"Cookie": cookie} if cookie else {})
    resp = conn.getresponse()
    return resp, resp.read()


def wait_state(conn, cookie, mid, want, timeout=10.0):
    """轮询资料库，等材料变到想要的状态；返回当时的材料条目（done 时材料不在列表，返回 None）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, data = get(conn, "/api/library", cookie)
        lib = json.loads(data)
        row = next((m for m in lib["materials"] if m["id"] == mid), None)
        if want == "done" and row is None:
            return lib  # 材料变课：从材料区毕业
        if row and row.get("state") == want:
            return row
        time.sleep(0.15)
    return False


# 假备课命令：收到（课名, 材料台, 课台），往课台写一份假课；讲稿里带 FAIL 就失败。
tmp = Path(tempfile.mkdtemp(prefix="lm-prep-"))
fake = tmp / "fake_prep.py"
fake.write_text("""
import json, sys, time
from pathlib import Path
ke, mr, lr = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
if not (mr / ke / "meta.json").exists():
    sys.exit(4)  # 备课台必须带 meta.json：teach.py 要从里面读标题和来源（SPEC-002 R9）
ld = lr / ke
ld.mkdir(parents=True, exist_ok=True)
(ld / "lesson.json").write_text(json.dumps({
    "title": "假课 " + ke, "source": "测试", "sections": [],
    "sentences": [{"id": 0, "start": 0, "end": 2.0, "text": "Hi.", "zh": "嗨", "speaker": "测试"}],
}, ensure_ascii=False), encoding="utf-8")
(ld / "audio.m4a").write_bytes(b"FAKE_M4A_PREP")
time.sleep(1.0)
t = mr / ke / "transcript.txt"   # 讲稿在备课台改叫 transcript.txt（pipeline 认的名字）
if t.exists() and "FAIL" in t.read_text(encoding="utf-8"):
    sys.exit(3)
""", encoding="utf-8")

os.environ.setdefault("FAKE_PREP_SLEEP", "1.0")
server = serve_mod.make_server(port=0, hosted_config={
    "invite": "测试邀请码", "data_dir": tmp / "data", "secure_cookie": False,
    "prep_command": [sys.executable, str(fake)],
    "materials_root": tmp / "stage_materials", "lessons_root": tmp / "stage_lessons",
})
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_address[1]


def upload(conn, cookie, name, script=""):
    q = "/api/upload?filename=" + quote(name) + (("&script=" + quote(script)) if script else "")
    conn.request("POST", q, body=b"FAKE_AUDIO_" * 20, headers={"Cookie": cookie})
    resp = conn.getresponse()
    return json.loads(resp.read())["material"]["id"]


try:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    resp, _ = post_json(conn, "/api/register", {"email": "p@example.com", "password": "passwd123", "invite": "测试邀请码"})
    cookie = (resp.getheader("Set-Cookie") or "").split(";")[0]

    # 备课中不许重复点
    mid1 = upload(conn, cookie, "slow.mp3", script="ok")
    resp, data = post_json(conn, "/api/prep", {"id": mid1}, cookie=cookie)
    check("点备课排队成功", resp.status == 200)
    resp, data = post_json(conn, "/api/prep", {"id": mid1}, cookie=cookie)
    check("备课中重复点被挡", resp.status == 409 and "不用重复点" in json.loads(data)["error"])
    row = wait_state(conn, cookie, mid1, "done")
    check("材料变课（材料区毕业）", row is not False)
    resp, data = post_json(conn, "/api/prep", {"id": mid1}, cookie=cookie)
    check("已备好的再点被挡", resp.status == 400)

    _, data = get(conn, "/api/library", cookie)
    lesson = json.loads(data)["lessons"][0]
    check("课区出现这节课", lesson["lesson"] == mid1 and lesson["title"] == f"假课 {mid1}" and lesson["duration"] == 2.0)
    resp, data = get(conn, f"/lessons/{mid1}/audio.m4a", cookie)
    check("备好的课音频取得到（账号路径）", resp.status == 200 and data == b"FAKE_M4A_PREP")

    # 失败 → 重试
    mid2 = upload(conn, cookie, "bad.mp3", script="FAIL")
    post_json(conn, "/api/prep", {"id": mid2}, cookie=cookie)
    row = wait_state(conn, cookie, mid2, "failed")
    check("失败停在 failed、人话原因", bool(row) and row["state"] == "failed" and "备课没成功" in row["error"])
    base = Path(server.accounts.dir) / server.accounts.account_id("p@example.com")
    meta = json.loads((base / "materials" / mid2 / "meta.json").read_text(encoding="utf-8"))
    check("失败记了哪一步（运维用）", meta.get("failed_step") == "自定义命令")
    (base / "materials" / mid2 / "script.txt").write_text("修好了", encoding="utf-8")
    resp, _ = post_json(conn, "/api/prep", {"id": mid2}, cookie=cookie)
    check("失败后能重试", resp.status == 200)
    row = wait_state(conn, cookie, mid2, "done")
    check("重试后变课", row is not False)
    _, data = get(conn, "/api/library", cookie)
    check("资料库两节课都在", len(json.loads(data)["lessons"]) == 2)
finally:
    server.shutdown()
    server.server_close()
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n通过 {len(passes)} 项，未通过 {len(failures)} 项")
sys.exit(1 if failures else 0)
