"""体验版和开发版（specs/SPEC-008-stable-and-dev.md）的自动检查。

在临时目录里造一个真的 git 仓库（放真的 pipeline/serve.py、pipeline/stable_copy.py、start-player.bat、.gitignore），
在它旁边建真的体验版，真的切版本、真的起服务、真的走一遍「点更新 → 服务停 → 换版本 → 起回来」。
只有网页三个文件、课程文件是小样子（服务要取得到，内容无所谓）。不碰这台电脑上真的体验版和 8765 端口。

跑法：<pywork python> tests/test_stable_copy.py   （约半分钟，不连网）
用例名开头是规格里的验收编号（A40 起）；tests/test_docs.py 核对两边对得上。
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REAL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REAL / "pipeline"))
import stable_copy as sc  # noqa: E402

LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))
failures: list[str] = []
passes: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passes if ok else failures).append(name)
    print(f"  {'通过' if ok else '未通过'}　{name}" + (f"　{detail}" if detail else ""))


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
                   check=True, capture_output=True)


def commit(root: Path, message: str, tested: bool = True) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    if tested:
        sc.record_test_pass(root, 1)   # 当作 tests/test_player.py 对这一版全过了
    return sc.must_head(root)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def cache(root: Path) -> dict:
    return sc.read_json(root / "lessons" / "L1" / "explain_cache.json") or {}


def add_to_cache(root: Path, key: str, zh: str) -> None:
    write(root / "lessons" / "L1" / "explain_cache.json", json.dumps({**cache(root), key: {"zh": zh}}, ensure_ascii=False))


def sentences(*texts: str) -> str:
    return json.dumps({"sentences": [{"id": k + 1, "text": t} for k, t in enumerate(texts)]})


def get(port: int, path: str):
    try:
        with LOCAL.open(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def post(port: int, path: str):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=b"{}", method="POST")
    try:
        with LOCAL.open(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def wait_answer(port: int, seconds: float = 20):
    deadline = time.time() + seconds
    while time.time() < deadline:
        answer = sc.ask_version(port)
        if answer:
            return answer
        time.sleep(0.2)
    return None


def make_repo(tmp: Path) -> Path:
    dev = tmp / "Proj"
    for name in ("serve.py", "stable_copy.py"):
        write(dev / "pipeline" / name, (REAL / "pipeline" / name).read_text(encoding="utf-8"))
    for name in (".gitignore", "start-player.bat"):
        (dev / name).write_bytes((REAL / name).read_bytes())
    for name in ("index.html", "app.js", "style.css"):
        write(dev / "web" / name, f"<!-- {name} -->")
    write(dev / "tests" / "test_player.py", "# 小样子")
    write(dev / "lessons" / "L1" / "lesson.json", sentences("Hello.", "Bye."))
    write(dev / "lessons" / "L1" / "explain_cache.json", json.dumps({"1:0": {"zh": "你好"}}, ensure_ascii=False))
    subprocess.run(["git", "init", "-q", str(dev)], check=True)
    commit(dev, "第一版")
    sc.setup(dev)
    return dev


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="lm-stable-test-"))
    try:
        run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n通过 {len(passes)} 项，未通过 {len(failures)} 项")
    if failures:
        print("未通过：" + "、".join(failures))
    return 1 if failures else 0


def run(tmp: Path) -> None:
    print("\n【建体验版、入口、端口】")
    dev = make_repo(tmp)
    stable = sc.beside(dev)
    c1 = sc.must_head(dev)
    check("建体验版：在开发版旁边、有标记、停在测过的那一版",
          stable.parent == dev.parent and sc.is_stable(stable) and sc.head(stable) == c1 and not sc.is_stable(dev))

    bat = (REAL / "start-player.bat").read_bytes()
    lines = bat.decode("ascii", errors="replace").splitlines()
    runs = [x for x in lines if not x.lstrip().lower().startswith("rem") and ("stable_copy.py" in x or "call " in x)]
    check("A41 start-player.bat 是纯英文字符；转去体验版、起服务那两行都在同一行里退出；名字和代码里写的一样",
          all(b < 128 for b in bat) and len(runs) == 2 and all(x.rstrip().endswith("& exit /b") for x in runs)
          and f"%NAME%{sc.SUFFIX}\\{sc.MARKER}" in bat.decode("ascii"), " | ".join(x.strip()[:60] for x in runs))

    a, b = sc.page_url(), (time.sleep(0.01), sc.page_url())[1]
    check("A42 双击打开的地址每次不一样，都是 localhost:8765（学习记录按这个地址存）",
          a != b and a.startswith("http://localhost:8765/web/") and b.startswith("http://localhost:8765/web/"), f"{a}  {b}")

    refused = subprocess.run([sys.executable, str(dev / "pipeline" / "serve.py"), "8765"], capture_output=True,
                             text=True, encoding="utf-8", timeout=20)
    check("A43 开发版拿 8765 起服务被拒，8766 可以；体验版拿 8765 可以",
          refused.returncode == 2 and "8766" in refused.stdout and sc.port_refusal(dev, sc.DEV_PORT) is None
          and sc.port_refusal(stable, sc.PORT) is None, refused.stdout.strip()[:60])

    print("\n【钉版本】")
    write(dev / "web" / "app.js", "// 多了一个按钮")
    add_to_cache(dev, "1:1", "新写进仓库的讲解")
    commit(dev, "第二版", tested=False)
    (dev / sc.TESTED).unlink()
    refusals = []
    for what in ("多了一个按钮",):
        try:
            sc.invite(what, dev)
        except sc.Refused as e:
            refusals.append(("没跑过测试", str(e)))
    sc.record_test_pass(dev, 1)
    write(dev / "web" / "style.css", "/* 测完又改了一笔 */")
    c2b = commit(dev, "测完又改了一笔", tested=False)
    try:
        sc.invite("多了一个按钮", dev)
    except sc.Refused as e:
        refusals.append(("测的是别的代码", str(e)))
    sc.record_test_pass(dev, 1)
    for what in ("修了 3fa9c21 那个问题", "SPEC-008 R5 做完了", ""):
        try:
            sc.invite(what, dev)
        except sc.Refused as e:
            refusals.append((what or "空的", str(e)))
    check("A44 没跑过测试、测的是别的代码、那句话里有提交号规格号或者是空的，都拒绝钉",
          len(refusals) == 5 and not (stable / sc.INVITE).exists()
          and "还没有全过" in refusals[0][1] and "web/style.css" in refusals[1][1],
          "；".join(f"{k}→{v[:24]}" for k, v in refusals))
    pinned = sc.invite("多了一个按钮", dev)

    print("\n【体验版被改过】")
    add_to_cache(stable, "2:0", "孩子查过的")
    write(stable / "lessons" / "L1" / "tts" / "bailian_emily" / "bye_now.mp3", "ID3")
    runtime_only = sc.hand_changes(stable)
    write(stable / "web" / "index.html", "<!-- 有人手改了 -->")
    changed = sc.hand_changes(stable)
    ok = sc.apply_update(stable, check_running=False)
    said = (sc.read_json(stable / sc.OUTCOME) or {}).get("said", "")
    listed = any("web/index.html" in x for x in sc.status(dev))
    check("A40 体验版里有文件被改过：换版本拒绝、一个文件都不动、status 说出是哪个；孩子用出来的数据不算改过",
          runtime_only == [] and changed == ["web/index.html"] and not ok and sc.head(stable) == c1
          and "有人手改了" in (stable / "web" / "index.html").read_text(encoding="utf-8") and listed
          and "被改过" in said, said)
    git(stable, "checkout", "--", "web/index.html")

    print("\n【点「更新」：真起服务】")
    port = sc.free_port()
    plain = subprocess.Popen([sys.executable, str(stable / "pipeline" / "serve.py"), str(port)], cwd=stable,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        before = wait_answer(port) or {}
        code = post(port, "/api/update")
        time.sleep(0.5)
        alive = plain.poll() is None
    finally:
        plain.terminate()
        plain.wait(10)
    port = sc.free_port()
    managed = subprocess.Popen([sys.executable, str(stable / "pipeline" / "serve.py"), str(port), "--managed"],
                               cwd=stable, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _, answer = get(port, "/api/version") if wait_answer(port) else (0, {})
        accepted = post(port, "/api/update")
        exit_code = managed.wait(10)
    finally:
        if managed.poll() is None:
            managed.kill()
    raw = json.dumps(answer)
    check("A46 真起服务：双击起的（有人负责拉起来）才亮「更新」，点了回 202、服务以退出码 7 停下；"
          "不是双击起的不亮、点了拒绝、服务照跑；回答里没有钉住的那个提交",
          not before.get("update", {}).get("waiting") and code == 409 and alive
          and answer.get("update") == {"waiting": True, "what": "多了一个按钮"} and accepted == 202
          and exit_code == sc.EXIT_UPDATE and pinned[:7] not in raw and answer.get("version") == c1,
          f"拒绝 {code}；亮 {answer.get('update')}；点了 {accepted}；退出码 {exit_code}")

    print("\n【换版本：去的是钉住的那一版，孩子的数据留下】")
    write(dev / "web" / "app.js", "// 第三版，做了一半")
    commit(dev, "第三版")
    port = sc.free_port()
    loop = subprocess.Popen([sys.executable, str(stable / "pipeline" / "stable_copy.py"), "run", "--port", str(port),
                             "--no-browser"], cwd=stable, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        first = (wait_answer(port) or {}).get("version")
        clicked = post(port, "/api/update")
        deadline, back = time.time() + 60, None
        while time.time() < deadline:
            answer = sc.ask_version(port)
            if answer and answer.get("version") != first:
                back = answer
                break
            time.sleep(0.3)
    finally:
        loop.terminate()
        loop.wait(10)
    check("A45 钉完又提交了一笔（做了一半），点更新换过去的仍是钉住的那一版；启动循环把服务起回来了",
          first == c1 and clicked == 202 and back is not None and back.get("version") == pinned == c2b
          and sc.head(stable) == c2b and not back.get("update", {}).get("waiting"),
          f"回来后报的 {str((back or {}).get('version'))[:7]}，钉的 {pinned[:7]}")
    kid = cache(stable)
    check("A48 孩子查过的讲解和现读的朗读换完还在，新版本新写进去的讲解也在",
          kid.get("2:0", {}).get("zh") == "孩子查过的" and kid.get("1:1", {}).get("zh") == "新写进仓库的讲解"
          and (stable / "lessons" / "L1" / "tts" / "bailian_emily" / "bye_now.mp3").exists(),
          f"讲解 {sorted(kid)}")
    outcome = sc.read_json(stable / sc.OUTCOME) or {}
    check("换好之后留下一句「已经换好了：……」", outcome.get("ok") is True and outcome.get("said") == "已经换好了：多了一个按钮",
          outcome.get("said", ""))

    print("\n【换版本失败，退回原来那一版】")
    write(dev / "pipeline" / "serve.py", "这一行不是 Python\n")
    commit(dev, "服务起不来的一版")
    sc.invite("一个起不来的版本", dev)
    add_to_cache(stable, "2:1", "孩子又查了一个")
    kept = (stable / "lessons" / "L1" / "explain_cache.json").read_bytes()
    ok = sc.apply_update(stable, check_running=False)
    outcome = sc.read_json(stable / sc.OUTCOME) or {}
    check("A47 新版本的服务起不来：退回原来那一版，孩子的数据原样，留下一句人话",
          not ok and sc.head(stable) == c2b and sc.hand_changes(stable) == []
          and (stable / "lessons" / "L1" / "explain_cache.json").read_bytes() == kept
          and outcome.get("ok") is False and "还是原来那一版" in outcome.get("said", ""), outcome.get("said", ""))
    write(dev / "pipeline" / "serve.py", (REAL / "pipeline" / "serve.py").read_text(encoding="utf-8"))

    print("\n【什么时候不留孩子的讲解】")
    (dev / "lessons" / "L1" / "explain_cache.json").unlink()
    c4 = commit(dev, "改了展开的提示词，删掉讲解缓存")
    sc.invite("展开讲得更清楚了", dev)
    sc.apply_update(stable, check_running=False)
    dropped_deleted = sc.head(stable) == c4 and not (stable / "lessons" / "L1" / "explain_cache.json").exists()
    add_to_cache(dev, "1:0", "你好")
    commit(dev, "重新有了讲解缓存")
    sc.invite("讲解缓存回来了", dev)
    sc.apply_update(stable, check_running=False)
    add_to_cache(stable, "2:0", "孩子查过的")
    write(dev / "lessons" / "L1" / "lesson.json", sentences("Hello.", "Goodbye, everyone."))
    c6 = commit(dev, "改了第二句")
    sc.invite("第二句切得更准了", dev)
    sc.apply_update(stable, check_running=False)
    check("A49 新版本删了讲解缓存、或者改了这一集的句子，孩子查过的那一集不留，按新的重查",
          dropped_deleted and sc.head(stable) == c6 and "2:0" not in cache(stable) and "1:0" in cache(stable),
          f"删缓存后 {'没了' if dropped_deleted else '还在'}；改句子后 {sorted(cache(stable))}")

    print("\n【退回上一版】")
    before = sc.head(stable)
    back_to = sc.rollback(dev)
    invite = sc.read_json(stable / sc.INVITE) or {}
    sc.apply_update(stable, check_running=False)
    check("A50 rollback 把上一版钉回去，换过去就回到上一版",
          back_to != before and invite.get("what") == "退回上一版" and sc.head(stable) == back_to,
          f"{before[:7]} → {str(sc.head(stable))[:7]}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.exit(main())
