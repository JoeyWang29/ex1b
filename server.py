"""SecureFile server: asyncio + mutual TLS + SFAP/1.

Security properties implemented here
------------------------------------
1. Transport      : TLS 1.2/1.3 with a private CA, client certificate required,
                    so the server only talks to holders of a CA-signed cert.
2. Identity       : password (scrypt) AND certificate CN binding per account.
3. Authorisation  : every path is resolved inside the caller's home sandbox.
4. Availability   : per-IP / global connection caps, handshake and idle
                    timeouts, control-frame flood detection, login lockout,
                    per-role bandwidth budgets, bounded windows.
5. Integrity      : SHA-256 per transfer, atomic rename of ``.part`` on success.
6. Auditability   : every privileged action is written to SQLite.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import logging
import os
import signal
import ssl
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from auth import User, UserStore
from protocol import (Frame, FrameWriter, Flags, Msg, ProtocolError, build,
                      error_frame, peer_common_name, read_frame)
from ratelimit import PeerGuard, TokenBucket
from sandbox import Sandbox, SandboxError

LOG = logging.getLogger("sfap.server")

CHUNK = 256 * 1024
ACK_EVERY = 1024 * 1024
WINDOW = 4 * 1024 * 1024
KEEPALIVE_INTERVAL = 20.0
IDLE_TIMEOUT = 75.0
HANDSHAKE_TIMEOUT = 10.0
CTRL_FRAMES_PER_SEC = 200


@dataclass
class Limits:
    max_conn: int = 256
    max_conn_per_ip: int = 8
    fail_threshold: int = 5
    lock_seconds: int = 60
    max_streams: int = 4
    idle_timeout: float = IDLE_TIMEOUT
    keepalive: float = KEEPALIVE_INTERVAL


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 9443
    data_root: str = "run/data"
    users_db: str = "run/state/users.db"
    cert: str = "run/certs/server-cert.pem"
    key: str = "run/certs/server-key.pem"
    ca: str = "run/certs/ca-cert.pem"
    limits: Limits = field(default_factory=Limits)

    @classmethod
    def load(cls, path: str | None) -> "Config":
        cfg = cls()
        if path and Path(path).exists():
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            tls = raw.pop("tls", {})
            lim = raw.pop("limits", {})
            for key, value in raw.items():
                setattr(cfg, key, value)
            for key, value in tls.items():
                setattr(cfg, key, value)
            known = {f for f in Limits.__dataclass_fields__}
            for key, value in lim.items():
                if key in known:
                    setattr(cfg.limits, key, value)
        return cfg


@dataclass
class Upload:
    stream: int
    final: Path
    part: Path
    size: int
    sha_expected: str
    handle: Any
    hasher: Any
    received: int
    next_seq: int = 0
    unacked: int = 0
    started: float = field(default_factory=time.monotonic)
    last_ack: float = field(default_factory=time.monotonic)


class Session:
    """One authenticated (or authenticating) client connection."""

    def __init__(self, server: "FileServer", reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter) -> None:
        self.server = server
        self.reader = reader
        self.writer = writer
        self.out = FrameWriter(writer)
        peername = writer.get_extra_info("peername") or ("unknown", 0)
        self.ip = peername[0]
        self.peer = "%s:%s" % (peername[0], peername[1])
        self.tls = writer.get_extra_info("ssl_object")
        self.cert_cn = peer_common_name(self.tls)
        self.user: User | None = None
        self.box: Sandbox | None = None
        self.uploads: dict[int, Upload] = {}
        self.downloads: dict[int, asyncio.Task] = {}
        self.used_streams = 0
        self.bucket = TokenBucket(0)
        self.last_recv = time.monotonic()
        self.last_send = time.monotonic()
        self.closed = False
        self.blocked_until = 0.0

    # ------------------------------------------------------------------ io
    async def send(self, frame: Frame) -> None:
        await self.out.send(frame)
        self.last_send = time.monotonic()

    async def fail(self, code: str, message: str, **extra: Any) -> None:
        await self.send(error_frame(code, message, **extra))

    # ---------------------------------------------------------------- main
    async def run(self) -> None:
        LOG.info("connect %s cn=%s", self.peer, self.cert_cn)
        watchdog = asyncio.create_task(self._watchdog())
        try:
            await self._authenticate()
            await self._loop()
        except asyncio.CancelledError:
            raise
        except (ConnectionError, asyncio.IncompleteReadError):
            LOG.info("peer reset %s", self.peer)
        except PermissionError:
            LOG.warning("authentication rejected for %s", self.peer)
        except Exception:  # pragma: no cover - defensive
            LOG.exception("session crashed for %s", self.peer)
        finally:
            watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog
            await self._cleanup()

    async def _authenticate(self) -> None:
        user = None
        for attempt in range(3):
            frame = await asyncio.wait_for(self._read(), timeout=30)
            if frame is None:
                raise ConnectionError("closed during login")
            if frame.type != Msg.LOGIN_REQ:
                await self.fail("NOT_AUTH", "login required as the first frame")
                raise PermissionError("protocol violation")
            name = str(frame.body.get("user", ""))
            password = str(frame.body.get("pass", ""))
            lock_key_ip = f"ip:{self.ip}"
            lock_key_user = f"user:{name}"
            remain = max(await self.server.guard.is_locked(lock_key_ip),
                         await self.server.guard.is_locked(lock_key_user))
            if remain > 0:
                await self.fail("LOCKED", f"too many failures, retry in {remain:.0f}s")
                await asyncio.sleep(min(remain, 3))
                raise PermissionError("locked")

            user = self.server.users.authenticate(name, password)
            if user is None:
                await self.server.guard.record_failure(lock_key_ip)
                await self.server.guard.record_failure(lock_key_user)
                self.server.users.audit(name or "-", self.ip, "login", "bad credentials", False)
                await self.fail("AUTH_FAILED", "invalid credentials",
                                attempts_left=2 - attempt)
                continue
            if user.cert_cn and self.cert_cn != user.cert_cn:
                self.server.users.audit(user.name, self.ip, "login",
                                        f"cert cn {self.cert_cn} != {user.cert_cn}", False)
                await self.fail("DENIED", "client certificate is not bound to this account")
                raise PermissionError("cert mismatch")
            break
        else:
            raise PermissionError("too many attempts")

        assert user is not None
        await self.server.guard.reset(f"ip:{self.ip}")
        await self.server.guard.reset(f"user:{user.name}")
        self.user = user
        home = Path(self.server.cfg.data_root) / user.name
        self.box = Sandbox(home)
        self.bucket = TokenBucket(user.rate_bps)
        self.server.users.audit(user.name, self.ip, "login", f"role={user.role}", True)
        self.server.online[user.name] = self.server.online.get(user.name, 0) + 1
        await self.send(build(Msg.LOGIN_RESP, body={
            "ok": True,
            "user": user.name,
            "role": user.role,
            "home": user.name,
            "keepalive": self.server.cfg.limits.keepalive,
            "idle_timeout": self.server.cfg.limits.idle_timeout,
            "rate_bps": user.rate_bps,
            "max_streams": min(user.max_streams, self.server.cfg.limits.max_streams),
            "quota_mb": user.quota_mb,
            "chunk": CHUNK,
            "window": WINDOW,
            "server_time": int(time.time()),
            "tls": self.tls.version() if self.tls else "none",
            "cipher": self.tls.cipher()[0] if self.tls else "none",
        }))
        LOG.info("login ok %s role=%s tls=%s", user.name, user.role,
                 self.tls.version() if self.tls else "-")

    async def _read(self) -> Frame | None:
        frame = await read_frame(self.reader)
        if frame is not None:
            self.last_recv = time.monotonic()
        return frame

    async def _loop(self) -> None:
        window_start = time.monotonic()
        count = 0
        while not self.closed:
            timeout = self.server.cfg.limits.idle_timeout
            try:
                frame = await asyncio.wait_for(self._read(), timeout=timeout)
            except asyncio.TimeoutError:
                LOG.info("idle timeout %s", self.peer)
                return
            if frame is None:
                return
            count += 1
            if time.monotonic() - window_start > 1.0:
                if count > CTRL_FRAMES_PER_SEC:
                    self.server.users.audit(self.user.name if self.user else "-", self.ip,
                                            "flood", f"{count} frames/s", False)
                    await self.fail("RATE_LIMITED", "control frame flood detected")
                    return
                window_start, count = time.monotonic(), 0
            await self.dispatch(frame)

    async def dispatch(self, frame: Frame) -> None:
        t = frame.type
        if t == Msg.PING:
            await self.send(build(Msg.PONG, body={"ts": frame.body.get("ts", 0)}))
        elif t == Msg.PONG:
            pass
        elif t == Msg.LIST_REQ:
            await self.do_list(frame)
        elif t == Msg.STAT_REQ:
            await self.do_stat(frame)
        elif t == Msg.UPLOAD_REQ:
            await self.do_upload_open(frame)
        elif t == Msg.DATA:
            await self.do_upload_data(frame)
        elif t == Msg.UPLOAD_END:
            await self.do_upload_end(frame)
        elif t == Msg.DOWNLOAD_REQ:
            await self.do_download(frame)
        elif t == Msg.CANCEL:
            await self.do_cancel(frame)
        elif t == Msg.MKDIR_REQ:
            await self.do_mkdir(frame)
        elif t == Msg.DELETE_REQ:
            await self.do_delete(frame)
        elif t == Msg.RENAME_REQ:
            await self.do_rename(frame)
        elif t == Msg.BYE:
            await self.send(build(Msg.BYE_ACK))
            self.closed = True
        elif t == Msg.LOGIN_REQ:
            await self.fail("CONFLICT", "already authenticated", stream=frame.stream)
        else:
            await self.fail("BAD_FRAME", f"unsupported message type 0x{t:02x}", stream=frame.stream)

    # ------------------------------------------------------------- helpers
    def _path(self, rel: str, *, must_exist: bool = False) -> Path:
        assert self.box is not None
        return self.box.resolve(rel, must_exist=must_exist)

    def _check_streams(self) -> None:
        limit = min(self.user.max_streams if self.user else 2,
                    self.server.cfg.limits.max_streams)
        if self.used_streams >= limit:
            raise PermissionError(f"stream limit {limit} reached")

    def _dir_usage(self) -> int:
        assert self.box is not None
        total = 0
        for dirpath, _dirs, files in os.walk(self.box.root):
            for name in files:
                with contextlib.suppress(OSError):
                    total += os.path.getsize(os.path.join(dirpath, name))
        return total

    # -------------------------------------------------------------- handlers
    async def do_list(self, frame: Frame) -> None:
        try:
            target = self._path(str(frame.body.get("path", ".")), must_exist=True)
            if not target.is_dir():
                raise NotADirectoryError
            entries = []
            for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                if child.name.startswith(".") or child.name in ("users.db",):
                    continue
                stat = child.stat()
                entries.append({
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "size": 0 if child.is_dir() else stat.st_size,
                    "mtime": int(stat.st_mtime),
                })
            await self.send(build(Msg.LIST_RESP, body={
                "path": frame.body.get("path", "."), "entries": entries}))
        except FileNotFoundError:
            await self.fail("NOT_FOUND", "no such directory", stream=frame.stream, path=frame.body.get("path"))
        except (SandboxError, NotADirectoryError) as exc:
            await self.fail("DENIED", str(exc) or "not a directory", stream=frame.stream)

    async def do_stat(self, frame: Frame) -> None:
        try:
            target = self._path(str(frame.body.get("path", "")), must_exist=True)
            if target.is_dir():
                raise IsADirectoryError
            digest = hashlib.sha256()
            with target.open("rb") as fh:
                while chunk := fh.read(1024 * 1024):
                    digest.update(chunk)
            await self.send(build(Msg.STAT_RESP, body={
                "path": frame.body.get("path"), "size": target.stat().st_size,
                "sha256": digest.hexdigest()}))
        except FileNotFoundError:
            await self.fail("NOT_FOUND", "no such file", stream=frame.stream)
        except (SandboxError, IsADirectoryError) as exc:
            await self.fail("DENIED", str(exc) or "not a file", stream=frame.stream)

    async def do_upload_open(self, frame: Frame) -> None:
        assert self.user is not None
        try:
            self._check_streams()
            rel = str(frame.body.get("path", ""))
            size = int(frame.body.get("size", -1))
            sha = str(frame.body.get("sha256", "")).lower()
            if size < 0 or len(sha) != 64:
                raise ValueError("size/sha256 required")
            target = self._path(rel)
            if target.exists() and target.is_dir():
                raise IsADirectoryError
            target.parent.mkdir(parents=True, exist_ok=True)
            if self.user.quota_mb:
                used = self._dir_usage()
                if used + size > self.user.quota_mb * 1024 * 1024:
                    await self.fail("TOO_LARGE", "quota exceeded", stream=frame.stream)
                    return

            part = target.with_suffix(target.suffix + ".part")
            offset = 0
            if frame.body.get("resume") or int(frame.body.get("offset", 0) or 0) < 0:
                if part.exists() and part.stat().st_size <= size:
                    offset = part.stat().st_size
            handle = part.open("r+b" if (part.exists() and offset) else "w+b")
            handle.seek(offset)
            hasher = hashlib.sha256()
            if offset:
                handle.seek(0)
                remaining = offset
                while remaining > 0:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    hasher.update(chunk)
                    remaining -= len(chunk)
                handle.seek(offset)

            stream = frame.stream or self.server.next_stream()
            if stream in self.uploads or stream in self.downloads:
                raise PermissionError("stream id already in use")
            self.uploads[stream] = Upload(stream=stream, final=target, part=part, size=size,
                                          sha_expected=sha, handle=handle, hasher=hasher,
                                          received=offset)
            self.used_streams += 1
            await self.send(build(Msg.UPLOAD_RESP, stream=stream,
                                  flags=Flags.RESUME if offset else 0,
                                  body={"stream": stream, "offset": offset, "chunk": CHUNK,
                                        "window": WINDOW, "size": size}))
            self.server.users.audit(self.user.name, self.ip, "upload-open",
                                    f"{rel} size={size} offset={offset}")
        except FileNotFoundError:
            await self.fail("NOT_FOUND", "target directory missing", stream=frame.stream)
        except (SandboxError, ValueError, IsADirectoryError, PermissionError) as exc:
            await self.fail("DENIED", str(exc) or "invalid upload request", stream=frame.stream)

    async def do_upload_data(self, frame: Frame) -> None:
        up = self.uploads.get(frame.stream)
        if up is None:
            await self.fail("NOT_FOUND", "unknown upload stream", stream=frame.stream)
            return
        if frame.seq != up.next_seq:
            await self._abort_upload(up, "out-of-order chunk")
            return
        data = frame.payload
        if up.received + len(data) > up.size:
            await self._abort_upload(up, "peer exceeds declared size")
            return
        await self.bucket.take(len(data))          # role-based bandwidth cap
        try:
            up.handle.write(data)
        except OSError as exc:
            await self._abort_upload(up, f"write failed: {exc.strerror}")
            return
        up.hasher.update(data)
        up.received += len(data)
        up.next_seq += 1
        up.unacked += len(data)
        now = time.monotonic()
        if up.unacked >= ACK_EVERY or (up.unacked and now - up.last_ack > 0.2):
            await self.send(build(Msg.DATA_ACK, stream=up.stream,
                                  body={"stream": up.stream, "acked": up.received}))
            up.unacked = 0
            up.last_ack = now

    async def do_upload_end(self, frame: Frame) -> None:
        up = self.uploads.get(frame.stream)
        if up is None:
            await self.fail("NOT_FOUND", "unknown upload stream", stream=frame.stream)
            return
        try:
            up.handle.flush()
            os.fsync(up.handle.fileno())
        except OSError:
            pass
        up.handle.close()
        actual = up.hasher.hexdigest()
        if up.received != up.size:
            self.uploads.pop(up.stream, None)
            self.used_streams -= 1
            self.server.users.audit(self.user.name, self.ip, "upload", "short transfer", False)
            await self.send(build(Msg.UPLOAD_RESP_END, stream=up.stream, flags=Flags.ERROR,
                                  body={"code": "INTEGRITY", "message": "size mismatch",
                                        "received": up.received, "expected": up.size}))
            return
        if actual != up.sha_expected:
            self.uploads.pop(up.stream, None)
            self.used_streams -= 1
            with contextlib.suppress(OSError):
                up.part.unlink()
            self.server.users.audit(self.user.name, self.ip, "upload", "sha256 mismatch", False)
            await self.send(build(Msg.UPLOAD_RESP_END, stream=up.stream, flags=Flags.ERROR,
                                  body={"code": "INTEGRITY", "message": "sha256 mismatch",
                                        "sha256": actual}))
            return
        os.replace(up.part, up.final)              # atomic publish
        self.uploads.pop(up.stream, None)
        self.used_streams -= 1
        elapsed = max(time.monotonic() - up.started, 1e-6)
        self.server.users.audit(self.user.name, self.ip, "upload",
                                f"{self.box.relative(up.final) if self.box else up.final.name}"
                                f" {up.size}B {up.size / elapsed / 1048576:.1f}MB/s")
        await self.send(build(Msg.UPLOAD_RESP_END, stream=up.stream,
                              body={"ok": True, "path": self.box.relative(up.final) if self.box else "",
                                    "size": up.size, "sha256": actual,
                                    "elapsed": round(elapsed, 3),
                                    "rate_mbps": round(up.size / elapsed / 1048576, 2)}))

    async def _abort_upload(self, up: Upload, reason: str) -> None:
        self.uploads.pop(up.stream, None)
        self.used_streams = max(0, self.used_streams - 1)
        with contextlib.suppress(OSError):
            up.handle.close()
        self.server.users.audit(self.user.name, self.ip, "upload", reason, False)
        await self.send(build(Msg.UPLOAD_RESP_END, stream=up.stream, flags=Flags.ERROR,
                              body={"code": "CONFLICT", "message": reason}))

    async def do_download(self, frame: Frame) -> None:
        assert self.user is not None
        try:
            self._check_streams()
            rel = str(frame.body.get("path", ""))
            target = self._path(rel, must_exist=True)
            if target.is_dir():
                raise IsADirectoryError
            offset = int(frame.body.get("offset", 0) or 0)
            size = target.stat().st_size
            if offset < 0 or offset > size:
                offset = 0
            task_id = frame.stream or self.server.next_stream()
            if task_id in self.downloads or task_id in self.uploads:
                raise PermissionError("stream id already in use")
            self.used_streams += 1
            self.server.users.audit(self.user.name, self.ip, "download-open",
                                    f"{rel} offset={offset}")
            task = asyncio.create_task(self._send_file(task_id, target, offset, size))
            self.downloads[task_id] = task
            task.add_done_callback(lambda _t, sid=task_id: self._download_done(sid))
        except FileNotFoundError:
            await self.fail("NOT_FOUND", "no such file", stream=frame.stream, path=frame.body.get("path"))
        except (SandboxError, IsADirectoryError, PermissionError) as exc:
            await self.fail("DENIED", str(exc) or "invalid download request", stream=frame.stream)

    def _download_done(self, stream: int) -> None:
        self.downloads.pop(stream, None)
        self.used_streams = max(0, self.used_streams - 1)

    async def _send_file(self, stream: int, path: Path, offset: int, size: int) -> None:
        digest = hashlib.sha256()
        sent = offset
        try:
            with path.open("rb") as fh:
                if offset:
                    fh.seek(0)
                    remaining = offset
                    while remaining > 0:
                        block = fh.read(min(1024 * 1024, remaining))
                        if not block:
                            break
                        digest.update(block)
                        remaining -= len(block)
                    fh.seek(offset)
                await self.send(build(Msg.DOWNLOAD_RESP, stream=stream, body={
                    "stream": stream, "path": path.name, "size": size,
                    "offset": offset, "chunk": CHUNK, "sha256_pending": True}))
                seq = 0
                while True:
                    chunk = fh.read(CHUNK)
                    if not chunk:
                        break
                    digest.update(chunk)
                    await self.bucket.take(len(chunk))
                    sent += len(chunk)
                    await self.send(build(Msg.DATA, stream=stream, seq=seq,
                                          body={"stream": stream, "offset": sent - len(chunk)},
                                          payload=chunk))
                    seq += 1
                await self.send(build(Msg.DATA, stream=stream, seq=seq, flags=Flags.LAST,
                                      body={"stream": stream, "eof": True,
                                            "sha256": digest.hexdigest(), "size": size}))
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await self.send(build(Msg.DATA, stream=stream, flags=Flags.LAST,
                                      body={"stream": stream, "cancelled": True,
                                            "offset": sent}))
            raise
        except (ConnectionError, OSError) as exc:
            LOG.info("download aborted %s: %s", path.name, exc)

    async def do_cancel(self, frame: Frame) -> None:
        sid = frame.stream or int(frame.body.get("stream", 0))
        task = self.downloads.pop(sid, None)
        if task:
            task.cancel()
        up = self.uploads.pop(sid, None)
        if up:
            with contextlib.suppress(OSError):
                up.handle.close()
            self.used_streams = max(0, self.used_streams - 1)
        await self.send(build(Msg.CANCEL, stream=sid, body={"ok": True, "stream": sid}))

    async def do_mkdir(self, frame: Frame) -> None:
        try:
            target = self._path(str(frame.body.get("path", "")))
            target.mkdir(parents=False, exist_ok=False)
            await self.send(build(Msg.MKDIR_RESP, body={"ok": True,
                                                        "path": frame.body.get("path")}))
        except (SandboxError, OSError) as exc:
            await self.fail("DENIED", str(exc) or "mkdir failed", stream=frame.stream)

    async def do_delete(self, frame: Frame) -> None:
        try:
            target = self._path(str(frame.body.get("path", "")), must_exist=True)
            if target.is_dir():
                target.rmdir()
            else:
                target.unlink()
            self.server.users.audit(self.user.name, self.ip, "delete", str(frame.body.get("path")))
            await self.send(build(Msg.DELETE_RESP, body={"ok": True}))
        except (SandboxError, OSError) as exc:
            await self.fail("DENIED", str(exc) or "delete failed", stream=frame.stream)

    async def do_rename(self, frame: Frame) -> None:
        try:
            src = self._path(str(frame.body.get("src", "")), must_exist=True)
            dst = self._path(str(frame.body.get("dst", "")))
            src.rename(dst)
            await self.send(build(Msg.RENAME_RESP, body={"ok": True}))
        except (SandboxError, OSError) as exc:
            await self.fail("DENIED", str(exc) or "rename failed", stream=frame.stream)

    # ------------------------------------------------------------- lifecycle
    async def _watchdog(self) -> None:
        interval = self.server.cfg.limits.keepalive
        try:
            while not self.closed:
                await asyncio.sleep(min(interval / 2, 5))
                now = time.monotonic()
                if now - self.last_recv > self.server.cfg.limits.idle_timeout:
                    LOG.info("watchdog: idle %s", self.peer)
                    self.writer.close()
                    return
                if now - self.last_send > interval and self.user is not None:
                    await self.send(build(Msg.PING, body={"ts": int(now * 1000)}))
        except (ConnectionError, asyncio.CancelledError):
            return

    async def _cleanup(self) -> None:
        for task in list(self.downloads.values()):
            task.cancel()
        for up in list(self.uploads.values()):
            with contextlib.suppress(OSError):
                up.handle.close()
        self.uploads.clear()
        self.downloads.clear()
        if self.user is not None:
            self.server.online[self.user.name] = max(0, self.server.online.get(self.user.name, 1) - 1)
        await self.out.close()


class FileServer:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.users = UserStore(cfg.users_db)
        self.guard = PeerGuard(cfg.limits.max_conn_per_ip, cfg.limits.max_conn,
                               cfg.limits.fail_threshold, cfg.limits.lock_seconds)
        self.online: dict[str, int] = {}
        self._stream = 0
        self.sessions: set[Session] = set()
        self._server: asyncio.AbstractServer | None = None

    def next_stream(self) -> int:
        self._stream = (self._stream + 1) % 0xFFFFFFFF or 1
        return self._stream

    def tls_context(self) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(self.cfg.cert, self.cfg.key)
        ctx.verify_mode = ssl.CERT_REQUIRED          # mutual authentication
        ctx.load_verify_locations(self.cfg.ca)
        ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20:!aNULL:!MD5")
        return ctx

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peername = writer.get_extra_info("peername") or ("unknown", 0)
        ip = peername[0]
        if not await self.guard.admit(ip):
            LOG.warning("reject %s: connection cap (active=%d total=%d)",
                        ip, self.guard.active.get(ip, 0), self.guard.total)
            writer.close()
            return
        session = Session(self, reader, writer)
        self.sessions.add(session)
        try:
            await session.run()
        finally:
            self.sessions.discard(session)
            await self.guard.release(ip)
            LOG.info("session end %s active=%d total=%d", ip,
                     self.guard.active.get(ip, 0), self.guard.total)

    async def serve(self) -> None:
        self._server = await asyncio.start_server(
            self.handle, self.cfg.host, self.cfg.port, ssl=self.tls_context(),
            ssl_handshake_timeout=HANDSHAKE_TIMEOUT, backlog=128, limit=2 ** 20)
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets or [])
        LOG.info("SFAP/1 server listening on %s (tls=mutual, data=%s)", addrs, self.cfg.data_root)

    async def shutdown(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for session in list(self.sessions):
            await session.out.close()
        self.users.close()


async def amain(cfg: Config) -> None:
    server = FileServer(cfg)
    await server.serve()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await server.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SecureFile server (SFAP/1 over TLS)")
    parser.add_argument("--config", default="config.server.json")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--data-root")
    parser.add_argument("--users-db")
    parser.add_argument("--cert")
    parser.add_argument("--key")
    parser.add_argument("--ca")
    parser.add_argument("--log", default="run/server.log")
    args = parser.parse_args(argv)

    cfg = Config.load(args.config)
    for name in ("host", "port", "data_root", "users_db", "cert", "key", "ca"):
        value = getattr(args, name, None)
        if value is not None:
            setattr(cfg, name, value)

    Path(cfg.data_root).mkdir(parents=True, exist_ok=True)
    Path(args.log).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(args.log, encoding="utf-8")],
    )
    try:
        asyncio.run(amain(cfg))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
