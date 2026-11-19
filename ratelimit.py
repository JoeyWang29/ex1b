"""Rate limiting and anti-abuse bookkeeping.

Three independent mechanisms keep the daemon useful under attack:

* ``TokenBucket``  - per-session byte budget, implements the "VIP 带宽" feature
                     and doubles as a flood brake on control frames.
* ``PeerGuard``    - per-IP connection caps plus a failure counter that locks an
                     origin for a while after repeated bad logins.
* ``counters``     - global session cap enforced before the TLS handshake.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict


class TokenBucket:
    """Classic token bucket; ``rate=0`` means unlimited."""

    __slots__ = ("rate", "capacity", "tokens", "updated", "lock")

    def __init__(self, rate_bps: int, burst: int | None = None) -> None:
        self.rate = rate_bps
        # A one-second burst would let a 24 MiB upload finish 1.5x faster than the
        # advertised rate, so cap the bucket at 1 MiB by default.
        self.capacity = float(burst if burst is not None else max(256 * 1024, min(rate_bps, 1 << 20)))
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.lock = asyncio.Lock()

    async def take(self, size: int) -> None:
        if self.rate <= 0 or size <= 0:
            return
        async with self.lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= size:
                    self.tokens -= size
                    return
                await asyncio.sleep(min((size - self.tokens) / self.rate, 0.5))


class PeerGuard:
    def __init__(self, max_per_ip: int = 8, max_total: int = 256,
                 fail_threshold: int = 5, lock_seconds: int = 60) -> None:
        self.max_per_ip = max_per_ip
        self.max_total = max_total
        self.fail_threshold = fail_threshold
        self.lock_seconds = lock_seconds
        self.active: dict[str, int] = defaultdict(int)
        self.total = 0
        self.failures: dict[str, list[float]] = defaultdict(list)
        self.locked_until: dict[str, float] = {}
        self.lock = asyncio.Lock()

    async def admit(self, ip: str) -> bool:
        async with self.lock:
            if self.total >= self.max_total:
                return False
            if self.active[ip] >= self.max_per_ip:
                return False
            self.active[ip] += 1
            self.total += 1
            return True

    async def release(self, ip: str) -> None:
        async with self.lock:
            self.active[ip] = max(0, self.active[ip] - 1)
            self.total = max(0, self.total - 1)

    async def is_locked(self, key: str) -> float:
        """Return remaining lock seconds (0 when free)."""
        async with self.lock:
            until = self.locked_until.get(key, 0.0)
            remain = until - time.monotonic()
            if remain <= 0:
                self.locked_until.pop(key, None)
                return 0.0
            return remain

    async def record_failure(self, key: str) -> int:
        async with self.lock:
            now = time.monotonic()
            window = [t for t in self.failures[key] if now - t < 300]
            window.append(now)
            self.failures[key] = window
            if len(window) >= self.fail_threshold:
                self.locked_until[key] = now + self.lock_seconds
                self.failures[key] = []
            return len(window)

    async def reset(self, key: str) -> None:
        async with self.lock:
            self.failures.pop(key, None)
            self.locked_until.pop(key, None)
