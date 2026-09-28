"""账号模块的单元检查（SPEC-009 v2：邮箱注册要邀请码、登录发会话、连错锁）。

跑法：<pywork python> tests/test_accounts.py   （不到 1 秒，不连网、不碰真数据；
账号和会话写在临时目录里，跑完就删。）
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from accounts import Accounts, AccountsError  # noqa: E402

failures: list[str] = []
passes: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passes if ok else failures).append(name)
    print(f"  {'通过' if ok else '未通过'}　{name}" + (f"　{detail}" if detail else ""))


def expect_error(name: str, fn, want_in_msg: str) -> None:
    try:
        fn()
    except AccountsError as e:
        check(name, want_in_msg in str(e), str(e))
        return
    check(name, False, "没报错")


tmp = Path(tempfile.mkdtemp(prefix="lm-accounts-"))
try:
    a = Accounts(tmp, invite_code="熟人圈")

    # 注册的四道闸
    expect_error("坏邮箱报错", lambda: a.register("not-an-email", "passwd123", "熟人圈"), "邮箱格式")
    expect_error("邀请码错报错", lambda: a.register("a@b.com", "passwd123", "错的"), "邀请码")
    expect_error("短密码报错", lambda: a.register("a@b.com", "123", "熟人圈"), "至少 6 位")
    a.register("A@B.com ", "passwd123", "熟人圈")  # 大小写和首尾空格都归一
    expect_error("重复注册报错", lambda: a.register("a@b.com", "other123", "熟人圈"), "已经注册")

    # 登录、会话
    expect_error("密码错报错", lambda: a.login("a@b.com", "wrong!!!"), "邮箱或密码")
    token = a.login(" a@B.COM", "passwd123")
    check("登录发令牌", bool(token))
    check("令牌查到邮箱", a.email_of(token) == "a@b.com")
    check("乱令牌查不到", a.email_of("no-such-token") is None)

    # 会话落盘（新实例也能查，模拟服务重启）
    a2 = Accounts(tmp, invite_code="熟人圈")
    check("重启后会话还在", a2.email_of(token) == "a@b.com")

    # 登出
    a.logout(token)
    check("登出后令牌失效", a.email_of(token) is None)

    # 连错锁：错满 10 次，之后对的密码也进不来
    for _ in range(9):
        try:
            a.login("a@b.com", "wrong!!!")
        except AccountsError:
            pass
    expect_error("第 10 次错触发锁", lambda: a.login("a@b.com", "wrong!!!"), "锁")
    expect_error("锁住时对密码也拒", lambda: a.login("a@b.com", "passwd123"), "锁")

    # 密码不明文落盘；邮箱转目录 id 稳定且不含邮箱本身
    raw = (tmp / "accounts.json").read_text(encoding="utf-8")
    check("密码明文不落盘", "passwd123" not in raw)
    aid = a.account_id("a@b.com")
    check("账号目录 id 稳定", aid == a2.account_id("A@B.COM") and len(aid) == 16 and "@" not in aid)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n通过 {len(passes)} 项，未通过 {len(failures)} 项")
sys.exit(1 if failures else 0)
