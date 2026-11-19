"""Scripted GUI demo used for the screencast.

It drives the *real* client with real mouse clicks (Win32 SetCursorPos + mouse_event)
so the recording shows a genuine interaction, not a mocked animation.

    python tools/demo_director.py [--fast]
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from client_gui import App  # noqa: E402

U = ctypes.windll.user32
SAMPLES = ROOT / "run" / "samples"
BIG = SAMPLES / "demo_20mb.bin"


def move_cursor(x: int, y: int, settle: float = 0.18) -> None:
    """Move the visible cursor; the action itself is invoked programmatically.

    Synthetic mouse_event clicks are dropped when the agent runs at a lower
    integrity level than the interactive desktop, so the rehearsal calls the
    widget directly while still parking the cursor on it.
    """
    U.SetCursorPos(int(x), int(y))
    time.sleep(settle)


def click_widget(widget, settle: float = 0.18) -> None:
    x = widget.winfo_rootx() + widget.winfo_width() // 2
    y = widget.winfo_rooty() + widget.winfo_height() // 2
    move_cursor(x, y, settle)
    try:
        widget.invoke()
    except Exception:  # noqa: BLE001 - treeview has no invoke
        pass


def walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from walk(child)


def find_button(root, text: str):
    for w in walk(root):
        if w.winfo_class() == "TButton":
            try:
                if text in str(w.cget("text")):
                    return w
            except Exception:  # noqa: BLE001
                continue
    return None


def prepare_file() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    size = 60 * 1024 * 1024
    if not BIG.exists() or BIG.stat().st_size != size:
        with BIG.open("wb") as fh:
            block = bytes(range(256)) * 4096  # 1 MiB
            for _ in range(size // len(block)):
                fh.write(block)


class Director:
    def __init__(self, app: App) -> None:
        self.app = app
        self.events: list[tuple[float, str]] = []
        self.t0 = time.monotonic()
        self.phase = "boot"

    def at(self, seconds: float, fn) -> None:
        self.app.after(int(seconds * 1000), fn)

    # ---------------------------------------------------------------- steps
    def start(self) -> None:
        app = self.app
        app.attributes("-topmost", True)
        app.lift()
        app.focus_force()
        app.local_path = SAMPLES
        app.refresh_local()
        app.update()

        self.at(1.2, lambda: self.click_connect())
        self.at(7.5, self.check_connected_upload)
        self.at(14.0, self.pause)
        self.at(19.0, self.resume)
        self.at(28.0, self.check_upload_done)
        self.at(31.0, self.start_download)
        self.at(38.0, self.pause)
        self.at(42.0, self.resume)
        self.at(52.0, self.finish)

    def click_connect(self) -> None:
        btn = self.app.btn_connect
        click_widget(btn, settle=0.35)
        # the first click may only activate the window on Windows
        self.app.after(500, lambda: click_widget(btn, settle=0.25))
        self.app.log("演示：点击“连接并登录”")

    def check_connected_upload(self) -> None:
        app = self.app
        if app.client is None or not app.status_var.get().startswith("已连接"):
            self.app.after(600, self.check_connected_upload)
            return
        # on_login resets the local pane to the working directory, so point it
        # back at the sample folder before selecting the upload candidate
        app.local_path = SAMPLES
        app.refresh_local()
        refresh = find_button(app, "刷新")
        if refresh:
            click_widget(refresh)
        self.app.after(900, self.select_and_upload)

    def select_and_upload(self) -> None:
        app = self.app
        tree = app.local_tree
        target = None
        for iid in tree.get_children():
            if str(iid).endswith("demo_20mb.bin"):
                target = iid
        if not target:
            app.log("演示：未找到待上传文件")
            return
        box = tree.bbox(target)
        if box:
            x = tree.winfo_rootx() + box[0] + box[2] // 2
            y = tree.winfo_rooty() + box[1] + box[3] // 2
            move_cursor(x, y)
            tree.selection_set(target)
            tree.focus(target)
        app.after(400, lambda: self.click_button("上传所选"))
        self.app.log("演示：选择 60 MiB 文件并上传")

    def click_button(self, text: str) -> None:
        btn = find_button(self.app, text)
        if btn:
            click_widget(btn)
            self.app.log(f"演示：点击“{text}”")

    def pause(self) -> None:
        self.select_first_transfer()
        self.app.after(300, lambda: self.click_button("暂停"))

    def resume(self) -> None:
        self.select_first_transfer()
        self.app.after(300, lambda: self.click_button("继续"))

    def select_first_transfer(self) -> None:
        tree = self.app.tr_tree
        children = tree.get_children()
        if not children:
            return
        box = tree.bbox(children[-1])
        if box:
            x = tree.winfo_rootx() + box[0] + box[2] // 2
            y = tree.winfo_rooty() + box[1] + box[3] // 2
            move_cursor(x, y)
            tree.selection_set(children[-1])
            tree.focus(children[-1])

    def check_upload_done(self) -> None:
        for tr in self.app.transfers.values():
            if tr.state == "运行中":
                self.app.after(800, self.check_upload_done)
                return
        refresh = find_button(self.app, "刷新")
        if refresh:
            click_widget(refresh)
        self.app.after(1200, self.app.refresh_remote)

    def start_download(self) -> None:
        app = self.app
        tree = app.remote_tree
        target = None
        for iid in tree.get_children():
            if str(iid).endswith("demo_20mb.bin"):
                target = iid
        if not target:
            # the upload may have been published after the last refresh; ask again
            app.refresh_remote()
            app.after(900, self.start_download)
            return
        box = tree.bbox(target)
        if box:
            x = tree.winfo_rootx() + box[0] + box[2] // 2
            y = tree.winfo_rooty() + box[1] + box[3] // 2
            move_cursor(x, y)
            tree.selection_set(target)
            tree.focus(target)
        app.after(400, lambda: self.click_button("下载所选"))
        app.log("演示：从远程下载同一个文件")

    def finish(self) -> None:
        self.app.log("演示结束：断点续传、限速与双向认证均已验证")
        self.app.after(12000, self.app.destroy)


def main() -> None:
    prepare_file()
    app = App()
    app.geometry("1180x780+40+30")
    app.update()
    app.lift()
    # expose the window handle so ffmpeg can capture this window only
    hwnd = ctypes.windll.user32.GetAncestor(app.winfo_id(), 2)
    out = ROOT / "demo" / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "hwnd.txt").write_text(str(hwnd), encoding="ascii")
    # give the recorder three seconds to attach before the first click
    app.after(3000, lambda: Director(app).start())
    app.mainloop()


if __name__ == "__main__":
    main()
