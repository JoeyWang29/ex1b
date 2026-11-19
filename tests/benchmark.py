"""Bandwidth / throughput benchmark per role and per direction.

    python tests/benchmark.py --port 9443

Produces the numbers used in the report's performance section:
* alice is ``vip``  (8 MiB/s bucket)
* bob   is ``normal`` (2 MiB/s bucket)
* download is throttled by the server bucket; upload is throttled by the server
  withholding ACKs, which closes the sender's 4 MiB window.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from client_core import SecureFileClient, TransferControl  # noqa: E402

CERTS = ROOT / "run" / "certs"
WORK = ROOT / "run" / "benchtmp"
SIZE = 24 * 1024 * 1024  # overridden by --size


def make_file(path: Path, size: int) -> None:
    if path.exists() and path.stat().st_size == size:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    block = os.urandom(1024 * 1024)
    with path.open("wb") as fh:
        for _ in range(size // len(block)):
            fh.write(block)
        fh.write(block[: size % len(block)])


def mk(user: str, port: int) -> SecureFileClient:
    return SecureFileClient("127.0.0.1", port, str(CERTS / "ca-cert.pem"),
                            str(CERTS / f"client-{user}-cert.pem"),
                            str(CERTS / f"client-{user}-key.pem"), server_hostname="localhost")


async def measure(user: str, password: str, port: int) -> tuple[float, float]:
    src = WORK / "bench.bin"
    make_file(src, SIZE)
    c = mk(user, port)
    await c.connect()
    info = await c.login(user, password)

    t0 = time.monotonic()
    await c.upload(str(src), "bench/bench.bin", TransferControl())
    up = SIZE / (time.monotonic() - t0) / 1024 / 1024

    dst = WORK / f"bench-{user}.bin"
    dst.unlink(missing_ok=True)
    (WORK / f"bench-{user}.bin.part").unlink(missing_ok=True)
    t0 = time.monotonic()
    await c.download("bench/bench.bin", str(dst), TransferControl())
    down = SIZE / (time.monotonic() - t0) / 1024 / 1024
    await c.close()
    print(f"  {user:<6} role={info['role']:<6} limit={info['rate_bps'] / 1048576:>4.0f} MiB/s "
          f"upload={up:>5.1f} MiB/s download={down:>5.1f} MiB/s")
    return up, down


async def main(port: int, rounds: int = 3, size_mib: int = 24) -> int:
    global SIZE
    SIZE = size_mib * 1024 * 1024
    print(f"payload = {SIZE // 1048576} MiB, {rounds} round(s) per role")
    results = {}
    for user, pw in (("alice", "Alice@2026"), ("bob", "Bob@2026")):
        ups, downs = [], []
        for _ in range(rounds):
            up, down = await measure(user, pw, port)
            ups.append(up)
            downs.append(down)
        results[user] = (statistics.mean(ups), statistics.mean(downs))
        print(f"  -> {user} mean upload {results[user][0]:.1f} / download {results[user][1]:.1f} MiB/s")
    ratio_up = results["alice"][0] / max(results["bob"][0], 1e-6)
    ratio_down = results["alice"][1] / max(results["bob"][1], 1e-6)
    print(f"\nvip / normal ratio: upload {ratio_up:.2f}x, download {ratio_down:.2f}x "
          f"(configured 4.00x)")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9443)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--size", type=int, default=24, help="payload size in MiB")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.port, args.rounds, args.size)))
