"""Developer helper: launch the GUI, auto-connect, save screenshots for the report.

    python tools/shot.py [out_dir]
Not part of the delivered client.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import ImageGrab  # noqa: E402

from client_gui import App  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "docs" / "figures")
OUT.mkdir(parents=True, exist_ok=True)
SAMPLES = ROOT / "run" / "samples"


def grab(app: App, name: str) -> None:
    app.lift()
    app.attributes("-topmost", True)
    app.update_idletasks()
    app.update()
    time.sleep(0.5)
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    full = ImageGrab.grab(all_screens=True)
    scale = full.size[0] / app.winfo_screenwidth()   # Windows DPI virtualisation
    box = (int(x * scale), int(y * scale), int((x + w) * scale), int((y + h) * scale))
    img = full.crop(box)
    path = OUT / name
    img.save(path)
    print("saved", path, img.size)


def stage_transfer(app: App) -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    big = SAMPLES / "demo_20mb.bin"
    size = 60 * 1024 * 1024
    if not big.exists() or big.stat().st_size != size:
        with big.open("wb") as fh:
            for _ in range(size // 1024):
                fh.write(b"\xa5" * 1024)
    app.local_path = SAMPLES
    app.refresh_local()
    app.update()
    for iid in app.local_tree.get_children():
        if iid.endswith("demo_20mb.bin"):
            app.local_tree.selection_set(iid)
    app.on_upload()


def pause_transfer(app: App) -> None:
    children = app.tr_tree.get_children()
    if children:
        app.tr_tree.selection_set(children[0])
        app.on_pause()


def main() -> None:
    app = App()
    app.geometry("1180x780+40+30")
    app.update()
    grab(app, "gui_login.png")
    app.after(300, app.on_connect)
    app.after(4000, lambda: grab(app, "gui_connected.png"))
    app.after(4400, lambda: stage_transfer(app))
    app.after(6000, lambda: grab(app, "gui_transfer.png"))
    app.after(6500, lambda: pause_transfer(app))
    app.after(7400, lambda: grab(app, "gui_paused.png"))
    app.after(8000, app.destroy)
    app.mainloop()


if __name__ == "__main__":
    main()
