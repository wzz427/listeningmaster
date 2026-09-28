"""邮箱账号：注册（要邀请码）、登录、会话——SPEC-009 v2。

为什么单独立文件（2026-09-28）：serve.py 原是给一家用的本地小服务；账号是对外版的地基。
先把账号写稳、单独测（tests/test_accounts.py），再接进 serve.py 的对外模式。
密码只存 PBKDF2 哈希，明文绝不落盘；会话落盘，服务重启不掉线。
数据住 LM_DATA_DIR 环境变量指的目录（默认 server-data/，已进 .gitignore）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SESSION_DAYS = 30          # 会话有效期（SPEC-009）
LOCK_FAILS = 10            # 连错这么多次就锁
LOCK_SECONDS = 600         # 锁十分钟
PBKDF2_ITERS = 60_000


class AccountsError(Exception):
    """给用户看的错误：str(err) 直接回给页面，不带任何内部细节。"""


class Accounts:
    def __init__(self, data_dir: str | Path, invite_code: str):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._file = self.dir / "accounts.json"
        self._sessions_file = self.dir / "sessions.json"
        self._invite = invite_code
        self._fails: dict[str, list] = {}  # email -> [连错次数, 锁到时间戳]

    # ---------- 落盘 ----------

    @staticmethod
    def _write(path: Path, obj) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)  # 原子替换，写一半断电不毁原文件

    def _load(self) -> dict:
        if not self._file.exists():
            return {}
        return json.loads(self._file.read_text(encoding="utf-8"))

    def _load_sessions(self) -> dict:
        if not self._sessions_file.exists():
            return {}
        return json.loads(self._sessions_file.read_text(encoding="utf-8"))

    # ---------- 注册、登录 ----------

    def register(self, email: str, password: str, invite: str) -> None:
        email = email.strip().lower()
        if not EMAIL_RE.match(email):
            raise AccountsError("邮箱格式不对")
        if invite != self._invite:
            raise AccountsError("邀请码不对")
        if len(password) < 6:
            raise AccountsError("密码至少 6 位")
        data = self._load()
        if email in data:
            raise AccountsError("这个邮箱已经注册过了")
        salt = secrets.token_hex(8)
        data[email] = {"salt": salt, "hash": self._hash(password, salt), "created": int(time.time())}
        self._write(self._file, data)

    def login(self, email: str, password: str) -> str:
        """验对发会话令牌（给 cookie 用），验错递增连错计数、满了锁十分钟。"""
        email = email.strip().lower()
        fails, locked_until = self._fails.setdefault(email, [0, 0.0])
        if locked_until > time.time():
            raise AccountsError("错得太多，锁十分钟，稍后再试")
        row = self._load().get(email)
        ok = row is not None and hmac.compare_digest(self._hash(password, row["salt"]), row["hash"])
        if not ok:
            fails += 1
            if fails >= LOCK_FAILS:
                self._fails[email] = [0, time.time() + LOCK_SECONDS]
                raise AccountsError("错得太多，锁十分钟，稍后再试")
            self._fails[email] = [fails, locked_until]
            raise AccountsError("邮箱或密码不对")
        self._fails[email] = [0, 0.0]
        token = secrets.token_urlsafe(24)
        sessions = self._load_sessions()
        now = time.time()
        sessions = {t: v for t, v in sessions.items() if v["expires"] > now}  # 顺手清过期
        sessions[token] = {"email": email, "expires": now + SESSION_DAYS * 86400}
        self._write(self._sessions_file, sessions)
        return token

    def logout(self, token: str) -> None:
        sessions = self._load_sessions()
        if token in sessions:
            del sessions[token]
            self._write(self._sessions_file, sessions)

    def email_of(self, token: str) -> str | None:
        """会话令牌 -> 邮箱；无效或过期回 None。"""
        row = self._load_sessions().get(token)
        if row is None or row["expires"] < time.time():
            return None
        return row["email"]

    def account_id(self, email: str) -> str:
        """账号目录名：邮箱哈希成稳定短 id，避免邮箱里的怪字符当路径。"""
        return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]

    @staticmethod
    def _hash(password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERS).hex()
