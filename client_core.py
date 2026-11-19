"""SecureFile client core: TLS transport, frame multiplexing, file transfers.

The GUI never blocks on I/O: :class:`AsyncWorker` owns a private event loop in a
background thread and hands results back through ``concurrent.futures``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import hashlib
import os
import ssl
import threading
import time
from pathlib import Path
from typing import Any, Callable

from protocol import Frame, FrameWriter, Flags, Msg, ProtocolError, build, read_frame

CHUNK = 256 * 1024
WINDOW = 4 * 1024 * 1024


class ServerError(Exception):
    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.extra = extra


class TransferAborted(Exception):
    def __init__(self, reason: str, offset: int = 0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.offset = offset


class TransferControl:
    """Cooperative pause / cancel switch shared with the GUI."""

    def __init__(self) -> None:
        self.cancelled = False
        self.paused = False
        self.reason = ""

    def cancel(self, reason: str = "用户取消") -> None:
        self.cancelled = True
        self.reason = reason

    def pause(self) -> None:
        self.cancelled = True
        self.paused = True
        self.reason = "已暂停"

    @property
    def stopped(self) -> bool:
        return self.cancelled


class SecureFileClient:
    def __init__(self, host: str, port: int, ca: str, cert: str, key: str,
                 server_hostname: str | None = None) -> None:
        self.host = host
        self.port = port
        self.ca = ca
        self.cert = cert
        self.key = key
        self.server_hostname = server_hostname or host
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.out: FrameWriter | None = None
        self.queues: dict[int, asyncio.Queue] = {}
        self.acks: dict[int, dict[str, Any]] = {}
        self.dead: set[int] = set()
        self._sid = 0
        self._read_task: asyncio.Task | None = None
        self._ping_task: asyncio.Task | None = None
        self.rtt_ms: float = 0.0
        self.last_rx = time.monotonic()
        self.info: dict[str, Any] = {}
        self.keepalive = 20.0
        self.closed = False

    # ------------------------------------------------------------- transport
    def _tls(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=self.ca)
        ctx.load_cert_chain(self.cert, self.key)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx

    async def connect(self, timeout: float = 10.0) -> None:
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port, ssl=self._tls(),
                                    server_hostname=self.server_hostname),
            timeout=timeout,
        )
        self.out = FrameWriter(self.writer)
        self._read_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        self.closed = True
        if self._ping_task:
            self._ping_task.cancel()
        if self.writer:
            try:
                if self.out:
                    await asyncio.wait_for(self.out.send(build(Msg.BYE)), timeout=1.0)
            except (ConnectionError, OSError, asyncio.TimeoutError):
                pass
            with contextlib.suppress(Exception):
                self.writer.close()
            # Do not await wait_closed(): the TLS shutdown handshake can stall on
            # Windows and the FIN is already queued by close().
            await asyncio.sleep(0)
        if self._read_task:
            self._read_task.cancel()
            with contextlib.suppress(Exception):
                await self._read_task

    def _next_stream(self) -> int:
        self._sid = (self._sid + 1) % 0xFFFFFFFE + 1
        return self._sid

    def _queue(self, stream: int) -> asyncio.Queue:
        q = self.queues.get(stream)
        if q is None:
            q = asyncio.Queue()
            self.queues[stream] = q
        return q

    async def send(self, frame: Frame) -> None:
        assert self.out is not None
        await self.out.send(frame)

    async def _read_loop(self) -> None:
        assert self.reader is not None
        try:
            while True:
                frame = await read_frame(self.reader)
                if frame is None:
                    break
                self.last_rx = time.monotonic()
                await self._route(frame)
        except (ConnectionError, OSError, ProtocolError, asyncio.CancelledError):
            pass
        finally:
            self.closed = True
            # Wake every pending waiter instead of letting it burn its timeout.
            for q in list(self.queues.values()):
                with contextlib.suppress(Exception):
                    q.put_nowait(build(Msg.ERROR, body={"code": "CLOSED",
                                                        "message": "连接已关闭"}))

    async def _route(self, frame: Frame) -> None:
        t = frame.type
        if t == Msg.PING:
            await self.send(build(Msg.PONG, body={"ts": frame.body.get("ts", 0)}))
            return
        if t == Msg.PONG:
            sent = frame.body.get("ts")
            if isinstance(sent, (int, float)):
                self.rtt_ms = max(0.0, time.monotonic() * 1000 - sent)
            return
        if t == Msg.DATA_ACK:
            state = self.acks.get(frame.stream)
            if state is not None:
                state["acked"] = int(frame.body.get("acked", 0))
                state["event"].set()
            return
        if frame.stream in self.dead:
            return
        q = self._queue(frame.stream)
        await q.put(frame)

    async def _ping_loop(self) -> None:
        try:
            while not self.closed:
                await self.send(build(Msg.PING, body={"ts": time.monotonic() * 1000}))
                await asyncio.sleep(self.keepalive)
                if time.monotonic() - self.last_rx > self.keepalive * 3:
                    self.closed = True
                    if self.writer:
                        self.writer.close()
                    return
        except (ConnectionError, OSError, asyncio.CancelledError):
            return

    async def request(self, frame: Frame, timeout: float = 20.0) -> Frame:
        q = self._queue(frame.stream)
        await self.send(frame)
        try:
            resp = await asyncio.wait_for(q.get(), timeout)
        except asyncio.TimeoutError:
            raise ServerError("TIMEOUT", "服务器响应超时") from None
        if resp.type == Msg.ERROR or (resp.flags & Flags.ERROR):
            extra = {k: v for k, v in resp.body.items() if k not in ("code", "message")}
            raise ServerError(resp.body.get("code", "ERROR"),
                              resp.body.get("message", "请求失败"), **extra)
        return resp

    # ------------------------------------------------------------------ auth
    async def login(self, user: str, password: str) -> dict[str, Any]:
        resp = await self.request(build(Msg.LOGIN_REQ, body={
            "user": user, "pass": password, "client": "securefile-gui", "proto": 1}), timeout=20)
        self.info = resp.body
        self.keepalive = float(resp.body.get("keepalive", 20))
        self._ping_task = asyncio.create_task(self._ping_loop())
        return resp.body

    def tls_summary(self) -> str:
        if not self.writer:
            return "-"
        obj = self.writer.get_extra_info("ssl_object")
        if obj is None:
            return "-"
        cert = obj.getpeercert() or {}
        cn = "-"
        for rdn in cert.get("subject", ()):
            for k, v in rdn:
                if k == "commonName":
                    cn = v
        return f"{obj.version()} / {obj.cipher()[0]} / CN={cn}"

    # -------------------------------------------------------------- file ops
    async def list_dir(self, path: str = ".") -> dict[str, Any]:
        resp = await self.request(build(Msg.LIST_REQ, body={"path": path}))
        return resp.body

    async def stat_file(self, path: str) -> dict[str, Any]:
        resp = await self.request(build(Msg.STAT_REQ, body={"path": path}))
        return resp.body

    async def mkdir(self, path: str) -> None:
        await self.request(build(Msg.MKDIR_REQ, body={"path": path}))

    async def delete(self, path: str) -> None:
        await self.request(build(Msg.DELETE_REQ, body={"path": path}))

    async def rename(self, src: str, dst: str) -> None:
        await self.request(build(Msg.RENAME_REQ, body={"src": src, "dst": dst}))

    async def _hash_file(self, path: Path) -> tuple[int, str]:
        loop = asyncio.get_running_loop()

        def work() -> tuple[int, str]:
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as fh:
                while chunk := fh.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            return size, digest.hexdigest()

        return await loop.run_in_executor(None, work)

    async def upload(self, local: str, remote: str, control: TransferControl,
                     on_progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
        src = Path(local)
        size, sha = await self._hash_file(src)
        stream = self._next_stream()
        resp = await self.request(build(Msg.UPLOAD_REQ, stream=stream, flags=Flags.RESUME, body={
            "path": remote, "size": size, "sha256": sha, "resume": True}))
        offset = int(resp.body.get("offset", 0))
        state = {"acked": offset, "event": asyncio.Event()}
        self.acks[stream] = state
        sent = offset
        try:
            with src.open("rb") as fh:
                fh.seek(offset)
                seq = 0
                while True:
                    if control.stopped:
                        raise TransferAborted(control.reason, sent)
                    chunk = fh.read(CHUNK)
                    if not chunk:
                        break
                    while sent - state["acked"] >= WINDOW:
                        state["event"].clear()
                        if sent - state["acked"] >= WINDOW and not control.stopped:
                            try:
                                await asyncio.wait_for(state["event"].wait(), timeout=10)
                            except asyncio.TimeoutError:
                                raise ServerError("STALLED", "发送窗口长时间未被确认") from None
                    await self.send(build(Msg.DATA, stream=stream, seq=seq, payload=chunk))
                    seq += 1
                    sent += len(chunk)
                    if on_progress:
                        on_progress(sent, size)
            if control.stopped:
                raise TransferAborted(control.reason, sent)
            done = await self.request(build(Msg.UPLOAD_END, stream=stream, flags=Flags.LAST,
                                            body={"sha256": sha}), timeout=120)
            return done.body
        except TransferAborted:
            with contextlib.suppress(Exception):
                await self.send(build(Msg.CANCEL, stream=stream, body={"stream": stream}))
            raise
        finally:
            self.acks.pop(stream, None)
            self.dead.add(stream)

    async def download(self, remote: str, local: str, control: TransferControl,
                       on_progress: Callable[[int, int], None] | None = None,
                       resume: bool = True) -> dict[str, Any]:
        dest = Path(local)
        part = dest.with_suffix(dest.suffix + ".part")
        offset = 0
        if resume and part.exists():
            offset = part.stat().st_size
        stream = self._next_stream()
        q = self._queue(stream)
        if offset:
            resp = await self.request(build(Msg.DOWNLOAD_REQ, stream=stream,
                                            body={"path": remote, "offset": offset}))
            size = int(resp.body.get("size", 0))
            digest = hashlib.sha256()
            with part.open("rb") as fh:
                while chunk := fh.read(1024 * 1024):
                    digest.update(chunk)
        else:
            resp = await self.request(build(Msg.DOWNLOAD_REQ, stream=stream,
                                            body={"path": remote, "offset": 0}))
            size = int(resp.body.get("size", 0))
            digest = hashlib.sha256()
            part.unlink(missing_ok=True)
        received = offset
        try:
            with part.open("ab") as fh:
                while True:
                    if control.stopped:
                        raise TransferAborted(control.reason, received)
                    frame = await q.get()
                    if frame.type == Msg.ERROR:
                        raise ServerError(frame.body.get("code", "ERROR"),
                                          frame.body.get("message", "下载失败"))
                    if frame.type != Msg.DATA:
                        continue
                    if frame.payload:
                        fh.write(frame.payload)
                        digest.update(frame.payload)
                        received += len(frame.payload)
                        if on_progress:
                            on_progress(received, size)
                    if frame.body.get("cancelled"):
                        raise TransferAborted("服务端已取消", received)
                    if frame.body.get("eof"):
                        fh.flush()
                        os.fsync(fh.fileno())
                        actual = digest.hexdigest()
                        if frame.body.get("sha256") and actual != frame.body["sha256"]:
                            raise ServerError("INTEGRITY", "下载内容校验失败")
                        break
            os.replace(part, dest)
            return {"ok": True, "size": received, "sha256": digest.hexdigest()}
        except TransferAborted:
            with contextlib.suppress(Exception):
                await self.send(build(Msg.CANCEL, stream=stream, body={"stream": stream}))
            raise
        finally:
            self.dead.add(stream)
            self.queues.pop(stream, None)

    async def cancel(self, stream: int) -> None:
        self.dead.add(stream)
        try:
            await self.send(build(Msg.CANCEL, stream=stream, body={"stream": stream}))
        except (ConnectionError, OSError):
            pass


class AsyncWorker:
    """Owns an event loop in a daemon thread so Tk stays responsive."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="sfap-io", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro) -> concurrent.futures.Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)
