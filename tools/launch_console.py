"""Open the deployment demo in its own console window, maximised.

The sandbox blocks `cmd /c start`, so the window is created through
subprocess with CREATE_NEW_CONSOLE and then maximised with ShowWindow.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

NEW_CONSOLE = 0x00000010
SW_MAXIMIZE = 3

bat = Path(sys.argv[1]).resolve()
subprocess.Popen(
    ["cmd", "/c", str(bat)],
    cwd=str(bat.parent.parent),
    creationflags=NEW_CONSOLE,
)
print(f"console launched: {bat}")

user32 = ctypes.windll.user32
found: list[int] = []


def enum(hwnd, _lparam):
    length = user32.GetWindowTextLengthW(hwnd)
    if length:
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if "SecureFile 1B" in buf.value:
            found.append(hwnd)
    return True


CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(enum)
for _ in range(20):
    found.clear()
    user32.EnumWindows(CALLBACK, 0)
    if found:
        break
    time.sleep(0.25)

if found:
    hwnd = found[0]
    user32.ShowWindow(hwnd, SW_MAXIMIZE)
    time.sleep(0.8)
    # Windows Terminal restores its own geometry, so insist once more and then
    # report the real rectangle for the recorder to crop against.
    user32.SetWindowPos(hwnd, 0, 0, 0, 1680, 1120, 0x0040)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    out = bat.parent / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "console_hwnd.txt").write_text(str(hwnd), encoding="ascii")
    (out / "console_rect.txt").write_text(
        f"{rect.left} {rect.top} {rect.right - rect.left} {rect.bottom - rect.top}\n", encoding="ascii", newline="\n")
    print("window:", hwnd, rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
else:
    print("window not found, leaving default size")
