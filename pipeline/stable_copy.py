"""体验版和开发版（SPEC-008，决策 D33、D34、D55）。

三个地方、一套代码（D55）：
- 开发版：这个仓库目录，claude 改的那份，随时可能改到一半。
- 体验版：旁边的「<仓库目录名>-stable」（今天是 BayesAPP\\ListeningMaster-stable），是这个仓库的第二个工作目录，
  不挂分支，根上有标记文件 .lm-stable-copy。owner 自己测新版本用的就是它：跑的是网站（对外模式），
  http://localhost:8790/ 。里面一个字不手改，只经这个文件换版本。
- 正式版：线上网站，孩子和各家用。只发 owner 在体验版上验过、说「上」的那一版（docs/deploy-listen-app.md）。

用法：<pywork python> pipeline/stable_copy.py <命令>
  status                  体验版在哪一版、落后几笔、有没有被改过、有没有钉着一版等他点、服务开没开
  invite --what "<一句话>"  钉开发版当前的提交请 owner 验：他页面右上角的「更新」从灰亮起来，点了就换过去
  rollback                把上一版钉回去，同样由他点「更新」生效
  setup                   一次性：在旁边建体验版（换电脑、目录丢了时再跑）
  run [--port N] [--no-browser]
                          双击 start-trial.bat 跑的就是它：起网站；服务因为「更新」停下，就换版本、再起
  apply-update            换到钉住的那一版。run 在服务停下后自己调；体验版的服务没开时 claude 也可以手动跑

几条理由（细节在 SPEC-008）：
- 只换到钉住的那一版，不追开发版最新的：最新的可能做了一半。钉之前核对 tests/test_player.py 和
  tests/test_hosted_frontend.py 对这份代码跑过且全过——它们全过时记下代码指纹，这里拿指纹和要钉的提交比
  （实验二：换行符转换不影响指纹）。
- 起服务、换版本、再起服务的循环在 Python 里，不在 bat 里：换版本会改写 bat 自己，命令行会从旧位置接着读，
  执行出乱码命令（实验一）。这个文件自己也会被换掉，所以用到的东西都在开头 import 好；换完再起的服务是新文件。
- 体验版用出来的数据（点词补查、展开查到的讲解，现读的词组朗读，上传材料备课时的备课台）换版本时留下，
  也不算「体验版被改过」（R7）。账号和上传的材料在不进仓库的 server-data/ 里，换版本根本碰不到。
- 体验版网站的公共课就是这一版仓库里的 lessons/：课跟着版本走，点了「更新」新课才出现（R11）。
- 屏幕上不出现提交号：给页面的回答里没有钉住的那个提交，「一句话」里也不许带（R9）。
"""

import argparse
import fnmatch
import json
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MARKER = ".lm-stable-copy"          # 体验版根上的标记文件
SUFFIX = "-stable"                  # 体验版目录名 = 开发版目录名 + 它；start-trial.bat 里也写着
PORT = 8790                         # 体验版网站的端口。owner 的登录和学习记录按 localhost:8790 存在浏览器里，不许换（R3）
DEV_PORT = 8766                     # claude 在开发版里看播放器（本地模式，tests/test_player.py 也是这个模式）
DEV_SITE_PORT = 8791                # claude 在开发版里看网站（对外模式）
EXIT_UPDATE = 7                     # 服务因为「更新」停下时的退出码；run 认它
INVITE = ".stable-invite.json"      # 钉住的那一版（在体验版根上）
OUTCOME = ".stable-outcome.json"    # 上一次换版本成没成、给他看的那句话（在体验版根上）
HISTORY = ".stable-history.jsonl"   # 每换一次一行，rollback 靠它找上一版（在体验版根上）
TESTED = ".player-tests-passed.json"     # tests/test_player.py 全过时记下的代码指纹（在开发版根上）
SITE_TESTED = ".site-tests-passed.json"  # tests/test_hosted_frontend.py 全过时记下的（体验版跑的是网站，R4）
MUST_PASS = ((TESTED, "tests/test_player.py"), (SITE_TESTED, "tests/test_hosted_frontend.py"))
SITE_CONFIG = "server-config.json"  # 体验版网站的配置：不进仓库，体验版自己一份（ensure_site 建）
DATA_DIR = "server-data"            # 体验版网站的账号、上传的材料：不进仓库，换版本碰不到

# 我们自己放在体验版根上的文件：看「体验版有没有被改过」时按名字排掉。
# 不靠 .gitignore——那份规则住在被检出的提交里，切到一个还没有这几行的提交上，它们就成了「被改过」（量化项目踩过）。
OUR_OWN = {MARKER, INVITE, OUTCOME, HISTORY, "api-keys.txt", SITE_CONFIG}

# 体验版用着的时候服务会写的文件：讲解缓存、现读的朗读，还有上传材料点「备课」时的备课台
# （materials/<材料号>/、lessons/<材料号>/，材料号＝上传时刻 12 位数字＋6 位十六进制，备好了搬进账号目录）。
# 它们变了不算体验版被改过（R7）
RUNTIME = re.compile(r"lessons/[^/]+/(explain_cache\.json|tts/.+\.mp3)|(materials|lessons)/\d{12}-[0-9a-f]{6}/.+")

# 这些文件变了，网站就可能变：测试的指纹只算它们。文档改了不用重跑测试
CODE = ("web/", "pipeline/", "tests/")
CODE_FILES = ("start-trial.bat", "lessons/*/lesson.json")

# 「一句话」是给 owner 看的，不许带这些（R9）
NOT_FOR_SCREEN = re.compile(r"[0-9a-f]{7,}|SPEC|\b[RDA]\d+[a-z]?\b|commit|worktree|invite|stable|提交号", re.I)

# 问本机的服务不走代理：这台电脑设了 HTTP_PROXY，不关掉的话 127.0.0.1 的请求会被送去代理
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Refused(Exception):
    """不做，带着给人看的那句话。"""


class StepFailed(Exception):
    """换版本的某一步没成。"""


# ---------- 基础 ----------

def git(root: Path, *args: str, check: bool = True, stdin: str | None = None) -> str:
    done = subprocess.run(["git", "-C", str(root), *args], input=stdin, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    if check and done.returncode != 0:
        raise StepFailed(f"git {' '.join(args[:3])} 没成：{done.stderr.strip()[:300]}")
    return done.stdout


def head(root: Path) -> str | None:
    """这份代码现在是哪个提交；不是 git 目录就说不清（None），页面上就永远不报「旧了」（R8）。"""
    try:
        out = git(root, "rev-parse", "HEAD").strip()
    except (StepFailed, OSError):
        return None
    return out or None


def must_head(root: Path) -> str:
    commit = head(root)
    if not commit:
        raise Refused(f"{root} 说不清是哪个提交（不是 git 目录？）。")
    return commit


def is_stable(root: Path) -> bool:
    return (root / MARKER).is_file()


def beside(dev: Path) -> Path:
    return dev.parent / (dev.name + SUFFIX)


def dev_of(root: Path) -> Path:
    """体验版对应的开发版：这个仓库的主目录。"""
    if not is_stable(root):
        return root
    common = Path(git(root, "rev-parse", "--git-common-dir").strip())
    return (common if common.is_absolute() else root / common).resolve().parent


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def say(text: str) -> None:
    print(text, flush=True)


def page_url(port: int = PORT) -> str:
    """双击打开的地址。主机名必须是 localhost：登录和学习记录按「localhost:8790」存在浏览器里（R3）。
    带一个每次都不一样的尾巴，浏览器就不会把开着的旧页签拿出来充数（R2）；页面不读它。"""
    return f"http://localhost:{port}/web/?opened={time.time_ns() // 1_000_000}"


def ask_version(port: int, timeout: float = 1.0) -> dict | None:
    """问本机这个端口上的播放器服务是哪一版。没人答 → None；答了但不是新服务 → {}。"""
    try:
        with LOCAL.open(f"http://127.0.0.1:{port}/api/version", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return {}
    except (OSError, ValueError):
        return None


def port_taken(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def port_refusal(root: Path, port: int) -> str | None:
    """开发版不许占体验版的端口（R3）。"""
    if port == PORT and not is_stable(root) and is_stable(beside(root)):
        return (f"这是开发版，{PORT} 端口留给体验版（owner 的登录和学习记录按这个地址存）。"
                f"claude 自己看网站用 {DEV_SITE_PORT}：pipeline/serve.py --hosted --port {DEV_SITE_PORT}；"
                f"看播放器用 {DEV_PORT}：pipeline/serve.py {DEV_PORT}")
    return None


# ---------- 测过的是不是这一版（R4） ----------

def _is_code(path: str) -> bool:
    return path.startswith(CODE) or any(fnmatch.fnmatchcase(path, p) and path.count("/") == p.count("/")
                                        for p in CODE_FILES)


def working_fingerprint(root: Path) -> dict[str, str]:
    """工作区里那些文件的 git 指纹（换行符按仓库规则转换后算，和提交里的可以直接比）。"""
    files = [f for f in git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
             if f and _is_code(f) and (root / f).is_file()]
    hashes = git(root, "hash-object", "--stdin-paths", stdin="\n".join(files) + "\n").split()
    return dict(zip(files, hashes))


def commit_fingerprint(root: Path, commit: str) -> dict[str, str]:
    out = {}
    for row in git(root, "ls-tree", "-r", "-z", commit).split("\0"):
        if "\t" in row:
            meta, path = row.split("\t", 1)
            if _is_code(path):
                out[path] = meta.split()[2]
    return out


def record_test_pass(root: Path, passed: int, which: str = TESTED) -> None:
    """tests/test_player.py（which=TESTED）、tests/test_hosted_frontend.py（which=SITE_TESTED）全过时调：
    记下这次测的是哪份代码。"""
    write_json(root / which, {"at": now(), "passed": passed, "fingerprint": working_fingerprint(root)})


def untested(dev: Path, commit: str) -> str | None:
    """这个提交的代码有没有被播放器和网站两份测试完整跑过且全过；没有就说为什么。"""
    want = commit_fingerprint(dev, commit)
    for which, name in MUST_PASS:
        record = read_json(dev / which)
        if not record:
            return f"{name} 还没有全过的记录。先跑到全过再钉。"
        tested = record.get("fingerprint") or {}
        differ = sorted(p for p in set(tested) | set(want) if tested.get(p) != want.get(p))
        if differ:
            return (f"上一次全过的 {name}（{record.get('at')}）测的不是这一版，"
                    f"不一样的文件：{'、'.join(differ[:8])}{' 等' if len(differ) > 8 else ''}。重跑到全过再钉。")
    return None


# ---------- 体验版有没有被改过（R1） ----------

def hand_changes(stable: Path) -> list[str]:
    """体验版里被改过的文件，排掉我们自己的和体验版用出来的数据。"""
    rules = dev_of(stable) / ".gitignore"
    extra = ["-c", f"core.excludesfile={rules.as_posix()}"] if rules.is_file() else []
    entries = git(stable, *extra, "status", "--porcelain", "-z", "--untracked-files=all").split("\0")
    changed, skip = [], False
    for entry in entries:
        if skip or not entry:
            skip = False
            continue
        code, path = entry[:2], entry[3:]
        skip = code[0] in "RC"  # 改名的下一项是原来的名字
        if (path in OUR_OWN or path.endswith(".tmp") and path[:-4] in OUR_OWN or RUNTIME.fullmatch(path)
                or path.startswith(DATA_DIR + "/")):
            continue
        changed.append(path)
    return changed


# ---------- 孩子用出来的数据（R7） ----------

def _sentences(root: Path, lesson: str) -> list | None:
    data = read_json(root / "lessons" / lesson / "lesson.json") or {}
    return [[s.get("id"), s.get("text")] for s in data.get("sentences") or []] or None


def save_runtime(stable: Path, commit: str) -> dict:
    """换版本前：每一集的讲解缓存原样存一份（退回时放回去），再挑出孩子新查的（和提交里的比，多出来或不一样的）。"""
    saved = {}
    for cache in sorted((stable / "lessons").glob("*/explain_cache.json")):
        lesson = cache.parent.name
        current = read_json(cache) or {}
        committed = git(stable, "show", f"{commit}:lessons/{lesson}/explain_cache.json", check=False)
        try:
            base = json.loads(committed) if committed.strip() else {}
        except ValueError:
            base = {}
        saved[lesson] = {"bytes": cache.read_bytes(), "sentences": _sentences(stable, lesson),
                         "added": {k: v for k, v in current.items() if base.get(k) != v}}
    return saved


def merge_runtime(stable: Path, saved: dict) -> dict[str, int]:
    """换到新版本后：孩子查过的讲解并回去（新版本里有的以新版本为准）。
    新版本改了这一集的句子，那一集就不留、按新的重查（讲解按句子编号存，对不上了）。
    缓存 2026-11-03 起不进仓库（fcced66）：换版本时它不再被 checkout 删掉，句子变了要在这里主动删。"""
    kept = {}
    for lesson, s in saved.items():
        path = stable / "lessons" / lesson / "explain_cache.json"
        if _sentences(stable, lesson) != s["sentences"]:
            path.unlink(missing_ok=True)   # 没被 checkout 删掉（不进仓库），句子对不上了，主动删
            continue
        if not s["added"] or not path.exists():
            continue
        cache = read_json(path) or {}
        fresh = {k: v for k, v in s["added"].items() if k not in cache}
        if fresh:
            cache.update(fresh)
            path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")  # 和 explain.py 写的一样
            kept[lesson] = len(fresh)
    return kept


def put_back(stable: Path, saved: dict) -> None:
    """退回原来那一版之后：讲解缓存放回换之前的样子。"""
    for lesson, s in saved.items():
        path = stable / "lessons" / lesson / "explain_cache.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(s["bytes"])


# ---------- 换版本（R4 到 R7） ----------

def switch(stable: Path, commit: str) -> None:
    # --force：讲解缓存的改动已经存下了；挡路的未跟踪文件（新版本里正好也有的朗读）以新版本的为准
    git(stable, "checkout", "--force", "--detach", commit)


def copy_keys(stable: Path) -> None:
    """密钥文件不进仓库，体验版里要一份：从开发版拷，只比字节、不读出来（CLAUDE.md 红线）。"""
    src, dst = dev_of(stable) / "api-keys.txt", stable / "api-keys.txt"
    if src.is_file() and (not dst.is_file() or dst.read_bytes() != src.read_bytes()):
        shutil.copyfile(src, dst)


def ensure_site(stable: Path) -> list[str]:
    """体验版跑网站要的、不进仓库的两样：配置（server-config.json）和数据目录（server-data/：账号、上传的材料）。
    缺什么补什么，已有的一个字不动。只在本机 127.0.0.1 上开；公共课就是这一版仓库里的 lessons/（R11）；
    注册邀请码照开发版本机那份（没有就新起一个）——本机用的，不是线上那个。"""
    made = []
    if not (stable / SITE_CONFIG).is_file():
        invite = (read_json(dev_of(stable) / SITE_CONFIG) or {}).get("invite") or f"listen-{secrets.token_hex(3)}"
        write_json(stable / SITE_CONFIG, {
            "_说明": "体验版网站的配置（不进仓库）：只在本机开，公共课就是这一版仓库里的 lessons/（specs/SPEC-008-stable-and-dev.md）",
            "invite": invite, "port": PORT, "bind": "127.0.0.1", "data_dir": DATA_DIR, "shared_root": ".",
            "secure_cookie": False})
        made.append("网站配置")
    if not (stable / DATA_DIR).is_dir():
        (stable / DATA_DIR).mkdir()
        made.append("数据目录")
    return made


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def probe(root: Path, want: str) -> None:
    """在一个空闲端口上真起一次这份代码的网站：回答的是这一版，网页的三个文件都取得到，才算换好了。"""
    port = free_port()
    proc = subprocess.Popen([sys.executable, str(root / "pipeline" / "serve.py"), "--hosted", "--port", str(port)],
                            cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 30
        answer = None
        while time.time() < deadline:
            if proc.poll() is not None:
                raise StepFailed(f"新版本的服务起不来（退出码 {proc.returncode}）")
            answer = ask_version(port, timeout=2)
            if answer is not None:
                break
            time.sleep(0.2)
        if answer is None:
            raise StepFailed("新版本的服务 30 秒没起来")
        if answer.get("version") != want:
            raise StepFailed(f"新版本的服务报的不是这一版：{answer.get('version')}")
        for name in ("index.html", "app.js", "style.css"):
            with LOCAL.open(f"http://127.0.0.1:{port}/web/{name}", timeout=5) as r:
                if r.status != 200:
                    raise StepFailed(f"新版本取不到 web/{name}")
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def outcome(stable: Path, ok: bool, said: str) -> None:
    write_json(stable / OUTCOME, {"at": now(), "ok": ok, "said": said})


def apply_update(stable: Path = ROOT, check_running: bool = True) -> bool:
    """换到钉住的那一版。任何一步不成都回到原来那一版，并留下一句给他看的话（R6）。"""
    if not is_stable(stable):
        raise Refused("这是开发版，没有要换的。")
    if check_running and (ask_version(PORT) or {}).get("copy") == "stable":
        raise Refused("体验版的服务正开着：请 owner 点页面上的「更新」，或者等他关掉黑窗口再换。")
    invite = read_json(stable / INVITE)
    old = must_head(stable)
    if not invite or invite.get("commit") == old:
        say("没有要换的新版本。")
        return True
    new, what = invite["commit"], invite.get("what", "")
    changed = hand_changes(stable)
    if changed:
        say("体验版里这些文件被改过，没有换：\n" + "\n".join(f"    {p}" for p in changed[:20]))
        outcome(stable, False, "体验版里有文件被改过，这次没有换，还是原来那一版。告诉 claude，他来处理。")
        return False
    saved = save_runtime(stable, old)
    try:
        switch(stable, new)
        kept = merge_runtime(stable, saved)
        copy_keys(stable)
        ensure_site(stable)
        probe(stable, new)
    except Exception as e:  # noqa: BLE001  任何一步不成都要退回去，不许把人扔在半路
        say(f"没换成：{e}")
        try:
            switch(stable, old)
            put_back(stable, saved)
            say("已经退回原来那一版。")
        except Exception as back:  # noqa: BLE001
            say(f"退回原来那一版也没成：{back}。体验版现在停在哪一版说不清，告诉 claude。")
        outcome(stable, False, "新版本没有换成，还是原来那一版，照常能用。告诉 claude，他来处理。")
        return False
    with (stable / HISTORY).open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now(), "from": old, "to": new, "what": what}, ensure_ascii=False) + "\n")
    outcome(stable, True, f"已经换好了：{what}")
    say(f"换好了：{what}" + (f"（体验版里查过的讲解留下了 {sum(kept.values())} 条）" if kept else ""))
    return True


# ---------- claude 的命令 ----------

def invite(what: str, dev: Path = ROOT) -> str:
    """钉开发版当前的提交请 owner 验（R4）。"""
    if is_stable(dev):
        raise Refused("这是体验版，钉版本要在开发版里做。")
    stable = beside(dev)
    if not is_stable(stable):
        raise Refused(f"旁边还没有体验版（{stable}），先跑 setup。")
    what = what.strip()
    if not what or len(what) > 60:
        raise Refused("「这一版多了什么」要写一句，60 个字以内。")
    if NOT_FOR_SCREEN.search(what):
        raise Refused(f"「{what}」里有 owner 看不懂的内部词（提交号、规格号、英文术语），换成人话。")
    commit = must_head(dev)
    why = untested(dev, commit)
    if why:
        raise Refused(why)
    if head(stable) == commit:
        raise Refused("体验版已经是这一版了。")
    write_json(stable / INVITE, {"at": now(), "commit": commit, "what": what})
    (stable / OUTCOME).unlink(missing_ok=True)  # 上一次没换成的那句话不再挂着
    return commit


def rollback(dev: Path = ROOT) -> str:
    """把上一版钉回去（R10）：体验版现在这一版是从哪一版换过来的，就钉那一版。它当初换过来时测过。"""
    stable = beside(dev) if not is_stable(dev) else dev
    current = must_head(stable)
    rows = [json.loads(x) for x in (stable / HISTORY).read_text(encoding="utf-8").splitlines() if x.strip()] \
        if (stable / HISTORY).is_file() else []
    previous = next((r["from"] for r in reversed(rows) if r.get("to") == current and r.get("from")), None)
    if not previous:
        raise Refused("没有上一版可退。")
    write_json(stable / INVITE, {"at": now(), "commit": previous, "what": "退回上一版"})
    (stable / OUTCOME).unlink(missing_ok=True)
    return previous


def carry_runtime(dev: Path, stable: Path) -> int:
    """建体验版时：开发版里用出来、还没提交的讲解和朗读，带过去。"""
    count = 0
    for entry in git(dev, "status", "--porcelain", "-z", "--untracked-files=all").split("\0"):
        path = entry[3:]
        if not entry or not RUNTIME.fullmatch(path) or not (dev / path).is_file():
            continue
        dst = stable / path
        if path.endswith(".json"):
            mine, theirs = read_json(dev / path) or {}, read_json(dst) or {}
            fresh = {k: v for k, v in mine.items() if k not in theirs}
            if fresh:
                dst.write_text(json.dumps({**theirs, **fresh}, ensure_ascii=False, indent=1), encoding="utf-8")
                count += len(fresh)
        elif not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dev / path, dst)
            count += 1
    return count


def setup(dev: Path = ROOT) -> Path:
    """在旁边建体验版，停在开发版当前的提交（要求测过）。"""
    if is_stable(dev):
        raise Refused("这是体验版，setup 要在开发版里跑。")
    stable = beside(dev)
    if stable.exists():
        raise Refused(f"{stable} 已经在了。")
    commit = must_head(dev)
    why = untested(dev, commit)
    if why:
        raise Refused(why)
    git(dev, "worktree", "add", "--detach", str(stable), commit)
    (stable / MARKER).write_text("这是体验版：owner 测新版本用的那份（网站，http://localhost:8790/）。里面一个字不手改，"
                                 "换版本只经 pipeline/stable_copy.py（specs/SPEC-008-stable-and-dev.md）。\n",
                                 encoding="utf-8")
    copy_keys(stable)
    ensure_site(stable)
    carried = carry_runtime(dev, stable)
    probe(stable, commit)
    with (stable / HISTORY).open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now(), "from": None, "to": commit, "what": "建立体验版"}, ensure_ascii=False) + "\n")
    say(f"体验版建好了：{stable}" + (f"（从开发版带过去 {carried} 份用出来的数据）" if carried else ""))
    return stable


def status(dev: Path = ROOT) -> list[str]:
    stable = dev if is_stable(dev) else beside(dev)
    dev = dev_of(stable) if is_stable(stable) else dev
    if not is_stable(stable):
        return [f"旁边没有体验版（{stable}）。"]
    at = must_head(stable)
    lines = [f"体验版：{stable}",
             f"  在哪一版：{git(stable, 'log', '-1', '--format=%h %s', at).strip()}",
             f"  落后开发版：{git(dev, 'rev-list', '--count', f'{at}..HEAD').strip()} 笔"]
    changed = hand_changes(stable)
    lines.append("  被改过的文件：" + ("、".join(changed[:10]) if changed else "没有"))
    inv = read_json(stable / INVITE)
    if inv and inv.get("commit") != at:
        lines.append(f"  钉着等他点：{inv['commit'][:10]}「{inv.get('what')}」（{inv.get('at')}）")
    else:
        lines.append("  钉着等他点：没有" + ("（他已经换过去了）" if inv else ""))
    out = read_json(stable / OUTCOME)
    if out:
        lines.append(f"  上一次换版本：{'成了' if out.get('ok') else '没成'}，{out.get('said')}（{out.get('at')}）")
    who = ask_version(PORT)
    lines.append("  网站：" + ("没开" if who is None else f"开着（体验版，http://localhost:{PORT}/）" if who.get("copy") == "stable"
                              else f"{PORT} 上是别的服务（多半是旧的黑窗口）"))
    return lines


# ---------- 双击 start-trial.bat 跑的循环（R2、R5） ----------

def run(root: Path = ROOT, port: int = PORT, browser: bool = True) -> int:
    """起网站（对外模式）。体验版里起之前先补齐不进仓库的配置、数据目录和密钥（换电脑、owner 换了密钥都靠这一步跟上）。"""
    say("这是体验版。" if is_stable(root) else "这是开发版（旁边没有体验版）。")
    refusal = port_refusal(root, port)
    if refusal:
        say(refusal)
        return 2
    if port_taken(port):
        who = ask_version(port)
        if who and who.get("copy") == ("stable" if is_stable(root) else "hosted"):
            say("网站已经开着了，直接打开网页。这个窗口可以关掉。")
            if browser:
                webbrowser.open(page_url(port))
            return 0
        say(f"{port} 端口被另一个服务占着，多半是还开着的旧黑窗口。把它关掉，再双击一次 start-trial.bat。")
        input("按回车关掉这个窗口")
        return 1
    if is_stable(root):
        made = ensure_site(root)
        copy_keys(root)
        if made:
            say(f"补好了体验版的{'、'.join(made)}。")
    first = True
    while True:
        args = [sys.executable, str(root / "pipeline" / "serve.py"), "--hosted", "--port", str(port), "--managed"]
        if first and browser:
            args.append("--open")
        first = False
        code = subprocess.call(args, cwd=root)
        if code == EXIT_UPDATE:
            say("\n正在换到新版本……")
            try:
                apply_update(root, check_running=False)
            except Exception as e:  # noqa: BLE001  换不成也要把服务起回来
                say(f"没换成：{e}")
            say("")
            continue
        if code == 0:
            return 0
        say("\n网站的服务停了（出了错）。上面几行是原因，截个图给 claude。")
        input("按回车关掉这个窗口")
        return code


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser(description="体验版和开发版（SPEC-008）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("invite")
    p.add_argument("--what", required=True)
    sub.add_parser("rollback")
    sub.add_parser("setup")
    sub.add_parser("apply-update")
    p = sub.add_parser("run")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--no-browser", action="store_true")
    a = parser.parse_args()
    try:
        if a.cmd == "status":
            say("\n".join(status()))
        elif a.cmd == "invite":
            commit = invite(a.what)
            say(f"钉好了：{commit[:10]}「{a.what}」。跟 owner 说：可以更新了，体验版页面右上角的「更新」亮了，点一下。")
        elif a.cmd == "rollback":
            commit = rollback()
            say(f"上一版钉回去了：{commit[:10]}。请 owner 点体验版页面右上角亮着的「更新」。")
        elif a.cmd == "setup":
            setup()
        elif a.cmd == "apply-update":
            return 0 if apply_update() else 1
        elif a.cmd == "run":
            return run(port=a.port, browser=not a.no_browser)
    except Refused as e:
        say(f"没做：{e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
