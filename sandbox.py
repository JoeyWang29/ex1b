"""Path sandbox.

The server never hands a client-supplied string to ``open()``.  Every request is
resolved against the caller's home directory and then re-checked after symlink
resolution, so neither ``../../etc/passwd`` nor a planted symlink can escape.
"""

from __future__ import annotations

import os
from pathlib import Path

FORBIDDEN_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_REL_LEN = 240
MAX_NAME_LEN = 120


class SandboxError(Exception):
    pass


def normalise(rel: str) -> str:
    if not isinstance(rel, str) or not rel:
        raise SandboxError("empty path")
    if len(rel) > MAX_REL_LEN:
        raise SandboxError("path too long")
    if "\x00" in rel or any(ord(ch) < 0x20 for ch in rel):
        raise SandboxError("control character in path")
    # Reject absolute paths, UNC paths and Windows drive letters outright.
    if rel.startswith("/") or rel.startswith("\\") or (len(rel) > 1 and rel[1] == ":"):
        raise SandboxError("absolute paths are not allowed")
    rel = rel.replace("\\", "/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise SandboxError("parent traversal is not allowed")
    for part in parts:
        if len(part) > MAX_NAME_LEN:
            raise SandboxError("component too long")
        if part.split(".")[0].upper() in FORBIDDEN_NAMES:
            raise SandboxError("reserved device name")
        if part in (".part", "users.db", "users.db-wal", "users.db-shm"):
            raise SandboxError("reserved internal name")
    return "/".join(parts) or "."


class Sandbox:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, rel: str, *, must_exist: bool = False) -> Path:
        clean = normalise(rel)
        target = (self.root / clean).resolve()
        try:
            common = os.path.commonpath([str(target), str(self.root)])
        except ValueError:
            raise SandboxError("path escapes home") from None
        if os.path.normcase(common) != os.path.normcase(str(self.root)):
            raise SandboxError("path escapes home")
        if must_exist and not target.exists():
            raise FileNotFoundError(clean)
        return target

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix() or "."
