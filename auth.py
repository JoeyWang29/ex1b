"""User directory backed by SQLite.

Every statement in this module is parameterised.  No SQL text is ever built by
string concatenation, so payloads such as ``admin' OR '1'='1`` are treated as
literal data by the driver instead of being parsed as SQL.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 32
SALT_LEN = 16

ROLES = {
    "admin": {"rate_bps": 0, "max_streams": 8, "quota_mb": 0},
    "vip": {"rate_bps": 8 * 1024 * 1024, "max_streams": 4, "quota_mb": 4096},
    "normal": {"rate_bps": 2 * 1024 * 1024, "max_streams": 2, "quota_mb": 1024},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    name       TEXT PRIMARY KEY,
    role       TEXT NOT NULL DEFAULT 'normal',
    salt       BLOB NOT NULL,
    pwhash     BLOB NOT NULL,
    cert_cn    TEXT,
    quota_mb   INTEGER NOT NULL DEFAULT 1024,
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,
    user   TEXT,
    peer   TEXT,
    action TEXT NOT NULL,
    detail TEXT,
    ok     INTEGER NOT NULL
);
"""


@dataclass(slots=True)
class User:
    name: str
    role: str
    cert_cn: str | None
    quota_mb: int
    enabled: bool

    @property
    def rate_bps(self) -> int:
        return ROLES.get(self.role, ROLES["normal"])["rate_bps"]

    @property
    def max_streams(self) -> int:
        return ROLES.get(self.role, ROLES["normal"])["max_streams"]


def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    salt = salt or secrets.token_bytes(SALT_LEN)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N,
                            r=SCRYPT_R, p=SCRYPT_P, dklen=DKLEN, maxmem=64 * 1024 * 1024)
    return salt, digest


class UserStore:
    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create_user(self, name: str, password: str, role: str = "normal",
                    cert_cn: str | None = None, quota_mb: int | None = None) -> None:
        if role not in ROLES:
            raise ValueError(f"unknown role {role}")
        salt, digest = hash_password(password)
        quota = quota_mb if quota_mb is not None else ROLES[role]["quota_mb"]
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO users(name, role, salt, pwhash, cert_cn, quota_mb,"
                " enabled, created_at) VALUES (?,?,?,?,?,?,1,?)",
                (name, role, salt, digest, cert_cn, quota, time.strftime("%Y-%m-%dT%H:%M:%S")),
            )

    def set_password(self, name: str, password: str) -> None:
        salt, digest = hash_password(password)
        with self._conn:
            self._conn.execute("UPDATE users SET salt=?, pwhash=? WHERE name=?",
                               (salt, digest, name))

    def get(self, name: str) -> User | None:
        cur = self._conn.execute(
            "SELECT name, role, cert_cn, quota_mb, enabled FROM users WHERE name=?", (name,))
        row = cur.fetchone()
        if row is None:
            return None
        return User(name=row[0], role=row[1], cert_cn=row[2], quota_mb=row[3], enabled=bool(row[4]))

    def authenticate(self, name: str, password: str) -> User | None:
        cur = self._conn.execute(
            "SELECT name, role, salt, pwhash, cert_cn, quota_mb, enabled"
            " FROM users WHERE name=?", (name,))
        row = cur.fetchone()
        if row is None:
            # Burn a comparable amount of time so that "user not found" and
            # "wrong password" are indistinguishable through timing.
            hash_password(password, b"\x00" * SALT_LEN)
            return None
        name, role, salt, stored, cert_cn, quota, enabled = row
        _, candidate = hash_password(password, salt)
        if not hmac.compare_digest(candidate, stored):
            return None
        if not enabled:
            return None
        return User(name=name, role=role, cert_cn=cert_cn, quota_mb=quota, enabled=True)

    def audit(self, user: str | None, peer: str, action: str, detail: str = "", ok: bool = True) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO audit(ts, user, peer, action, detail, ok) VALUES (?,?,?,?,?,?)",
                (time.strftime("%Y-%m-%dT%H:%M:%S"), user, peer, action, detail, int(ok)),
            )


def seed_default(db_path: str) -> None:
    """Create the three demo accounts used by the report's test matrix."""
    store = UserStore(db_path)
    try:
        if store.get("alice") is None:
            store.create_user("alice", "Alice@2026", "vip", cert_cn="alice")
        if store.get("bob") is None:
            store.create_user("bob", "Bob@2026", "normal", cert_cn="bob")
        if store.get("admin") is None:
            store.create_user("admin", "Admin@2026", "admin", cert_cn=None)
    finally:
        store.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="manage SecureFile accounts")
    parser.add_argument("--db", default="../run/users.db")
    parser.add_argument("--init", action="store_true", help="create demo accounts")
    parser.add_argument("--add", nargs=2, metavar=("NAME", "PASSWORD"))
    parser.add_argument("--role", default="normal", choices=sorted(ROLES))
    parser.add_argument("--cert-cn", default=None)
    args = parser.parse_args()

    if args.init:
        seed_default(args.db)
        print(f"[ok] demo accounts written to {args.db}: alice/bob/admin")
    if args.add:
        s = UserStore(args.db)
        s.create_user(args.add[0], args.add[1], args.role, args.cert_cn)
        s.close()
        print(f"[ok] user {args.add[0]} created with role {args.role}")
