"""End-to-end and security test suite for SecureFile.

Runs against a live server (see run_tests.sh).  Every case prints PASS/FAIL and
the suite exits non-zero if any expectation is violated, so it can be used as a
CI gate and as the evidence table in the report.

    python tests/e2e.py --host 127.0.0.1 --port 9443
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from client_core import SecureFileClient, ServerError, TransferAborted, TransferControl  # noqa: E402

CERTS = ROOT / "run" / "certs"
WORK = ROOT / "run" / "testtmp"
RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name:<38} {detail}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def make_file(path: Path, size: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        remaining = size
        while remaining > 0:
            block = secrets.token_bytes(min(256 * 1024, remaining))
            fh.write(block)
            remaining -= len(block)
    return sha256(path)


def client(cert: str = "alice") -> SecureFileClient:
    return SecureFileClient("127.0.0.1", ARGS.port, str(CERTS / "ca-cert.pem"),
                            str(CERTS / f"client-{cert}-cert.pem"),
                            str(CERTS / f"client-{cert}-key.pem"), server_hostname="localhost")


async def case_tls_and_login() -> None:
    c = client()
    await c.connect()
    record("TLS 1.3 双向认证握手", "TLS" in c.tls_summary(), c.tls_summary())
    info = await c.login("alice", "Alice@2026")
    record("口令 + 证书绑定登录", info.get("user") == "alice",
           f"role={info.get('role')} keepalive={info.get('keepalive')}s")
    listing = await c.list_dir(".")
    record("目录列举", isinstance(listing.get("entries"), list),
           f"{len(listing.get('entries', []))} 项")
    await c.close()


async def case_bad_credentials() -> None:
    c = client()
    await c.connect()
    try:
        await c.login("alice", "wrong-password")
        record("错误口令被拒绝", False, "unexpected success")
    except ServerError as exc:
        record("错误口令被拒绝", exc.code == "AUTH_FAILED", exc.code)
    await c.close()

    c = client()
    await c.connect()
    try:
        await c.login("alice' OR '1'='1", "x' OR 'x'='x")
        record("SQL 注入登录被拒绝", False, "unexpected success")
    except ServerError as exc:
        record("SQL 注入登录被拒绝", exc.code in ("AUTH_FAILED", "LOCKED"), exc.code)
    await c.close()

    c = client("bob")  # bob 的证书配 alice 的账号
    await c.connect()
    try:
        await c.login("alice", "Alice@2026")
        record("证书与账号不匹配被拒绝", False, "unexpected success")
    except ServerError as exc:
        record("证书与账号不匹配被拒绝", exc.code in ("DENIED", "AUTH_FAILED"), exc.code)
    await c.close()


async def case_upload_download() -> None:
    src = WORK / "payload.bin"
    digest = make_file(src, 3 * 1024 * 1024 + 12345)
    c = client()
    await c.connect()
    await c.login("alice", "Alice@2026")
    t0 = time.monotonic()
    body = await c.upload(str(src), "demo/payload.bin", TransferControl())
    elapsed = time.monotonic() - t0
    record("上传 3 MiB 并校验 SHA-256", body.get("sha256") == digest,
           f"{elapsed:.2f}s  {3.0 / max(elapsed, 1e-6):.1f} MiB/s")

    remote_copy = WORK / "downloaded.bin"
    remote_copy.unlink(missing_ok=True)
    body = await c.download("demo/payload.bin", str(remote_copy), TransferControl())
    record("下载并还原 SHA-256", sha256(remote_copy) == digest,
           f"{remote_copy.stat().st_size} bytes")
    await c.close()


async def case_resume_upload() -> None:
    src = WORK / "big.bin"
    digest = make_file(src, 8 * 1024 * 1024)
    c = client()
    await c.connect()
    await c.login("alice", "Alice@2026")
    control = TransferControl()

    def progress(done: int, total: int) -> None:
        if done > total * 0.55:
            control.pause()

    try:
        await c.upload(str(src), "demo/resume.bin", control, progress)
    except TransferAborted:
        pass
    part = ROOT / "run" / "data" / "alice" / "demo" / "resume.bin.part"
    size_at_pause = part.stat().st_size if part.exists() else 0
    record("暂停时保留 .part 断点", size_at_pause > 0, f"{size_at_pause} bytes")

    body = await c.upload(str(src), "demo/resume.bin", TransferControl())
    final = ROOT / "run" / "data" / "alice" / "demo" / "resume.bin"
    record("断点续传后内容一致", final.exists() and sha256(final) == digest,
           f"resumed from {size_at_pause}")
    await c.close()

    control = TransferControl()
    c = client()
    await c.connect()
    await c.login("alice", "Alice@2026")

    def stop_early(done: int, total: int) -> None:
        if done > total * 0.5:
            control.pause()

    dst = WORK / "resume-down.bin"
    dst.unlink(missing_ok=True)
    (WORK / "resume-down.bin.part").unlink(missing_ok=True)
    try:
        await c.download("demo/resume.bin", str(dst), control, stop_early)
    except TransferAborted:
        pass
    got = (WORK / "resume-down.bin.part").stat().st_size if (WORK / "resume-down.bin.part").exists() else 0
    body = await c.download("demo/resume.bin", str(dst), TransferControl())
    record("下载断点续传", dst.exists() and sha256(dst) == digest, f"part {got} bytes → complete")
    await c.close()


async def case_concurrent() -> None:
    files = []
    for i in range(3):
        p = WORK / f"conc{i}.bin"
        files.append((p, make_file(p, 2 * 1024 * 1024 + i)))
    c = client()
    await c.connect()
    await c.login("alice", "Alice@2026")
    t0 = time.monotonic()
    tasks = [c.upload(str(p), f"demo/{p.name}", TransferControl()) for p, _ in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = time.monotonic() - t0
    ok = all(isinstance(r, dict) and r.get("ok") for r in results)
    record("单连接多流并发上传", ok, f"3 流 / {elapsed:.2f}s")
    if not ok:
        print("   detail:", results)
    await c.close()


async def case_path_traversal() -> None:
    c = client()
    await c.connect()
    await c.login("alice", "Alice@2026")
    src = WORK / "payload.bin"
    for remote in ("../escape.bin", "..\\escape.bin", "/etc/passwd", "C:\\Windows\\win.ini"):
        try:
            await c.upload(str(src), remote, TransferControl())
            record(f"越权路径被拒绝 {remote}", False, "unexpected success")
        except ServerError as exc:
            record(f"越权路径被拒绝 {remote}", exc.code == "DENIED", exc.code)
    try:
        await c.download("../../../../etc/passwd", str(WORK / "x.bin"), TransferControl())
        record("越权下载被拒绝", False, "unexpected success")
    except ServerError as exc:
        record("越权下载被拒绝", exc.code == "DENIED", exc.code)
    await c.close()


async def case_heartbeat() -> None:
    c = client()
    await c.connect()
    await c.login("alice", "Alice@2026")
    await asyncio.sleep(2.5)
    record("长连接心跳保活", not c.closed and c.rtt_ms >= 0, f"RTT {c.rtt_ms:.0f} ms")
    await c.close()


async def case_connection_cap() -> None:
    holders = []
    rejected = 0
    for _ in range(10):
        c = client()
        try:
            await c.connect(timeout=5)
            await c.login("alice", "Alice@2026")
            holders.append(c)
            await asyncio.sleep(0.05)
        except Exception:  # noqa: BLE001
            rejected += 1
    record("单 IP 连接数上限生效", rejected >= 1, f"{len(holders)} accepted / {rejected} rejected")
    for c in holders:
        await c.close()


async def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    cases = [case_tls_and_login, case_bad_credentials, case_upload_download,
             case_resume_upload, case_concurrent, case_path_traversal,
             case_heartbeat, case_connection_cap]
    for case in cases:
        started = time.monotonic()
        await case()
        print(f"       └ {case.__name__:<28} {time.monotonic() - started:6.2f}s")

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 78)
    print(f"TOTAL {passed}/{len(RESULTS)} passed")
    print("=" * 78)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9443)
    ARGS = parser.parse_args()
    raise SystemExit(asyncio.run(main()))
