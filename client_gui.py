"""SecureFile GUI: a Tk client for the SFAP/1 protocol.

Design notes
------------
* All network work runs in :class:`client_core.AsyncWorker`; the Tk thread only
  touches widgets.  Progress is passed through a ``queue.Queue`` that is drained
  by a 200 ms ``after`` tick, which is the only thread-safe way to touch Tk.
* A transfer row survives pausing: pressing 暂停 cancels the stream but keeps
  the byte offset, and 继续 re-opens the stream with ``offset`` so the server
  resumes from the partial ``.part`` file.
"""

from __future__ import annotations

import os
import queue
import time
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from client_core import (AsyncWorker, SecureFileClient, ServerError,
                         TransferAborted, TransferControl)

BG = "#ffffff"
PANEL = "#f6f7f9"
LINE = "#e3e6ea"
TEXT = "#1f2328"
MUTED = "#6b7280"
ACCENT = "#185FA5"
OK = "#0f6e56"
WARN = "#993c1d"

HERE = Path(__file__).resolve().parent
RUN = HERE / "run"


@dataclass
class Transfer:
    tid: int
    name: str
    direction: str
    local: str
    remote: str
    size: int
    control: TransferControl = field(default_factory=TransferControl)
    done: int = 0
    state: str = "等待"
    started: float = field(default_factory=time.monotonic)
    last_bytes: int = 0
    last_ts: float = field(default_factory=time.monotonic)
    speed: float = 0.0
    offset: int = 0
    note: str = ""


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SecureFile 1B  -  安全文件传输客户端 (SFAP/1 over mutual TLS)")
        self.geometry("1180x780")
        self.minsize(1020, 680)
        self.configure(bg=BG)

        self.worker = AsyncWorker()
        self.client: SecureFileClient | None = None
        self.user = ""
        self.role = ""
        self.remote_path = "."
        self.local_path = Path(os.getcwd())
        self.transfers: dict[int, Transfer] = {}
        self.events: queue.Queue = queue.Queue()
        self._tid = 0
        self._last_dir = RUN / "certs"

        self._init_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(200, self._pump)
        self.after(1000, self._tick)
        self.log("就绪。默认演示账号 alice / Alice@2026（证书 CN 必须为 alice）")

    # ------------------------------------------------------------------ style
    def _init_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 9))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 8))
        style.configure("Panel.TLabel", background=PANEL, foreground=MUTED, font=("Microsoft YaHei UI", 8))
        style.configure("Head.TLabel", background=BG, foreground=TEXT,
                        font=("Microsoft YaHei UI", 14, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("TButton", padding=(10, 4), borderwidth=0, focusthickness=0,
                        background="#eef1f4", foreground=TEXT)
        style.map("TButton", background=[("active", "#e2e7ec"), ("disabled", "#f2f3f5")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                        font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Accent.TButton", background=[("active", "#134b83")])
        style.configure("TEntry", fieldbackground="#ffffff", bordercolor=LINE, padding=4)
        style.configure("TCombobox", fieldbackground="#ffffff", padding=3)
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff",
                        rowheight=24, borderwidth=0, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", background=PANEL, foreground=MUTED,
                        font=("Microsoft YaHei UI", 8, "bold"), relief="flat", padding=4)
        style.map("Treeview", background=[("selected", "#dbeafe")],
                  foreground=[("selected", TEXT)])
        style.configure("TLabelframe", background=BG, bordercolor=LINE)
        style.configure("TLabelframe.Label", background=BG, foreground=MUTED,
                        font=("Microsoft YaHei UI", 8, "bold"))
        style.configure("TSeparator", background=LINE)
        style.configure("TNotebook", background=BG, borderwidth=0)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=3)
        self.rowconfigure(3, weight=2)

        head = ttk.Frame(self, padding=(18, 12, 18, 4))
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="SecureFile", style="Head.TLabel").pack(side="left")
        ttk.Label(head, text="  安全文件传输客户端 · 自定义应用层协议 SFAP/1 · 双向证书认证",
                  style="Sub.TLabel").pack(side="left", pady=(4, 0))
        self.tls_var = tk.StringVar(value="未连接")
        ttk.Label(head, textvariable=self.tls_var, style="Muted.TLabel").pack(side="right")

        conn = ttk.LabelFrame(self, text=" 连接与身份 ", padding=12)
        conn.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 8))

        row1 = ttk.Frame(conn)
        row1.pack(fill="x")
        self.host_var = tk.StringVar(value="127.0.0.1")
        self.port_var = tk.StringVar(value="9443")
        self.ca_var = tk.StringVar(value=str(self._last_dir / "ca-cert.pem"))
        self.cert_var = tk.StringVar(value=str(self._last_dir / "client-cert.pem"))
        self.key_var = tk.StringVar(value=str(self._last_dir / "client-key.pem"))

        for label, var, width in (("服务器", self.host_var, 14), ("端口", self.port_var, 7)):
            ttk.Label(row1, text=label).pack(side="left", padx=(0, 4))
            ttk.Entry(row1, textvariable=var, width=width).pack(side="left", padx=(0, 12))

        self.user_var = tk.StringVar(value="alice")
        self.pass_var = tk.StringVar(value="Alice@2026")
        ttk.Label(row1, text="用户").pack(side="left", padx=(0, 4))
        ttk.Entry(row1, textvariable=self.user_var, width=10).pack(side="left", padx=(0, 8))
        ttk.Label(row1, text="口令").pack(side="left", padx=(0, 4))
        ttk.Entry(row1, textvariable=self.pass_var, width=14, show="*").pack(side="left", padx=(0, 14))

        self.btn_connect = ttk.Button(row1, text="连接并登录", style="Accent.TButton",
                                      command=self.on_connect)
        self.btn_connect.pack(side="left")
        self.btn_disconnect = ttk.Button(row1, text="断开", command=self.on_disconnect,
                                         state="disabled")
        self.btn_disconnect.pack(side="left", padx=6)

        certs = ttk.Frame(conn)
        certs.pack(fill="x", pady=(10, 0))
        for index, (label, var) in enumerate((
                ("CA 证书", self.ca_var), ("客户端证书", self.cert_var), ("客户端私钥", self.key_var))):
            certs.columnconfigure(index, weight=1)
            cell = ttk.Frame(certs)
            cell.grid(row=0, column=index, sticky="ew", padx=(0, 12) if index < 2 else 0)
            ttk.Label(cell, text=label, style="Muted.TLabel").pack(anchor="w", pady=(0, 2))
            line = ttk.Frame(cell)
            line.pack(fill="x")
            ttk.Entry(line, textvariable=var).pack(side="left", fill="x", expand=True)
            ttk.Button(line, text="...", width=3,
                       command=lambda v=var, l=label: self._pick(v, l)).pack(side="left", padx=(4, 0))

        panes = ttk.Frame(self)
        panes.grid(row=2, column=0, sticky="nsew", padx=18)
        panes.columnconfigure(0, weight=1, uniform="pane")
        panes.columnconfigure(1, weight=1, uniform="pane")
        panes.rowconfigure(0, weight=1)

        self.local_tree = self._file_pane(panes, 0, "本地文件", "上传所选  ↑")
        self.remote_tree = self._file_pane(panes, 1, "远程文件", "下载所选  ↓")

        queue_frame = ttk.LabelFrame(self, text=" 传输队列 ", padding=(10, 6))
        queue_frame.grid(row=3, column=0, sticky="nsew", padx=18, pady=(8, 4))
        cols = ("name", "dir", "size", "progress", "speed", "state")
        self.tr_tree = ttk.Treeview(queue_frame, columns=cols, show="headings", height=5)
        for col, text, width, anchor in (
            ("name", "文件", 300, "w"), ("dir", "方向", 60, "center"),
            ("size", "大小", 90, "e"), ("progress", "进度", 220, "w"),
            ("speed", "速率", 100, "e"), ("state", "状态", 140, "w")):
            self.tr_tree.heading(col, text=text)
            self.tr_tree.column(col, width=width, anchor=anchor, stretch=(col in ("name", "progress")))
        self.tr_tree.pack(fill="both", expand=True, side="top")

        bar = ttk.Frame(queue_frame)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="暂停", command=self.on_pause).pack(side="left")
        ttk.Button(bar, text="继续", command=self.on_resume).pack(side="left", padx=6)
        ttk.Button(bar, text="取消", command=self.on_cancel).pack(side="left")
        ttk.Button(bar, text="清除已完成", command=self.on_clear).pack(side="left", padx=6)
        self.summary_var = tk.StringVar(value="无活动传输")
        ttk.Label(bar, textvariable=self.summary_var, style="Muted.TLabel").pack(side="right")

        logf = ttk.LabelFrame(self, text=" 运行日志 ", padding=(10, 4))
        logf.grid(row=4, column=0, sticky="ew", padx=18, pady=(4, 6))
        self.logbox = ScrolledText(logf, height=4, font=("Consolas", 9), bg="#fbfbfc",
                                   fg="#33383f", relief="flat", borderwidth=0, wrap="word")
        self.logbox.pack(fill="both", expand=True)
        self.logbox.configure(state="disabled")

        status = ttk.Frame(self, style="Panel.TFrame", padding=(18, 5))
        status.grid(row=5, column=0, sticky="ew")
        self.status_var = tk.StringVar(value="未连接")
        ttk.Label(status, textvariable=self.status_var, style="Panel.TLabel").pack(side="left")
        self.stream_var = tk.StringVar(value="")
        ttk.Label(status, textvariable=self.stream_var, style="Panel.TLabel").pack(side="right")

    def _file_pane(self, parent: ttk.Frame, col: int, title: str, action: str) -> ttk.Treeview:
        frame = ttk.LabelFrame(parent, text=f" {title} ", padding=(10, 8))
        frame.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col == 0 else (8, 0))

        top = ttk.Frame(frame)
        top.pack(fill="x", pady=(0, 6))
        path_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=path_var)
        entry.pack(side="left", fill="x", expand=True)
        tree = ttk.Treeview(frame, columns=("name", "size", "mtime"), show="headings", height=9)
        tree.heading("name", text="名称")
        tree.heading("size", text="大小")
        tree.heading("mtime", text="修改时间")
        tree.column("name", width=240, anchor="w")
        tree.column("size", width=90, anchor="e")
        tree.column("mtime", width=130, anchor="center")
        tree.tag_configure("dir", foreground=ACCENT)
        tree.pack(fill="both", expand=True)
        if col == 0:
            ttk.Button(top, text="上级", width=5, command=self.local_up).pack(side="left", padx=4)
            ttk.Button(top, text="刷新", width=5, command=self.refresh_local).pack(side="left")
            ttk.Button(top, text=action, style="Accent.TButton",
                       command=self.on_upload).pack(side="left", padx=6)
            self.local_path_var = path_var
            tree.bind("<Double-1>", self.on_local_open)
        else:
            ttk.Button(top, text="上级", width=5, command=self.remote_up).pack(side="left", padx=4)
            ttk.Button(top, text="刷新", width=5, command=self.refresh_remote).pack(side="left")
            ttk.Button(top, text="新建目录", width=8, command=self.on_mkdir).pack(side="left", padx=4)
            ttk.Button(top, text="删除", width=5, command=self.on_delete).pack(side="left")
            ttk.Button(top, text=action, style="Accent.TButton",
                       command=self.on_download).pack(side="left", padx=6)
            self.remote_path_var = path_var
            tree.bind("<Double-1>", self.on_remote_open)
        return tree

    # ------------------------------------------------------------------ utils
    def log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.logbox.configure(state="normal")
        self.logbox.insert("end", f"[{stamp}] {message}\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _pick(self, var: tk.StringVar, label: str) -> None:
        path = filedialog.askopenfilename(title=f"选择{label}", initialdir=str(self._last_dir))
        if path:
            var.set(path)

    def run_async(self, coro, on_done=None, on_error=None) -> None:
        fut = self.worker.submit(coro)

        def settle(f):
            try:
                result = f.result()
            except Exception as exc:  # noqa: BLE001 - surfaced to the user
                self.events.put(("error", on_error or self._default_error, exc))
            else:
                if on_done:
                    self.events.put(("ok", on_done, result))

        fut.add_done_callback(settle)

    def _default_error(self, exc: Exception) -> None:
        if isinstance(exc, ServerError):
            self.log(f"服务端拒绝：{exc.code} - {exc.message}")
            messagebox.showerror("操作失败", f"{exc.code}\n{exc.message}")
        elif isinstance(exc, TransferAborted):
            self.log(f"传输中止：{exc.reason}")
        else:
            self.log(f"异常：{exc!r}")
            messagebox.showerror("异常", str(exc))

    @staticmethod
    def fmt_size(num: float) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if abs(num) < 1024 or unit == "GB":
                return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
            num /= 1024
        return f"{num:.1f} GB"

    # ------------------------------------------------------------- connection
    def on_connect(self) -> None:
        if self.client:
            return
        self.btn_connect.configure(state="disabled")
        self.log(f"正在与 {self.host_var.get()}:{self.port_var.get()} 建立 TLS 连接 ...")
        self.client = SecureFileClient(
            self.host_var.get().strip(), int(self.port_var.get()),
            self.ca_var.get().strip(), self.cert_var.get().strip(),
            self.key_var.get().strip(), server_hostname=self.host_var.get().strip())

        def connected(_):
            self.tls_var.set(self.client.tls_summary())
            self.log(f"TLS 握手完成：{self.client.tls_summary()}")
            self.run_async(self.client.login(self.user_var.get().strip(), self.pass_var.get()),
                           self.on_login, self.on_connect_failed)

        self.run_async(self.client.connect(), connected, self.on_connect_failed)

    def on_login(self, info: dict) -> None:
        self.user = info.get("user", "")
        self.role = info.get("role", "")
        rate = info.get("rate_bps", 0)
        rate_txt = "不限速" if not rate else f"{rate / 1048576:.0f} MB/s"
        self.status_var.set(
            f"已连接 · {self.user}（{self.role}）· 配额 {info.get('quota_mb', 0)} MB · "
            f"限速 {rate_txt} · 并发流 {info.get('max_streams', 2)}")
        self.btn_disconnect.configure(state="normal")
        self.log(f"登录成功：{self.user} / {self.role} / {info.get('tls')} / {info.get('cipher')}")
        self.local_path = Path(os.getcwd())
        self.refresh_local()
        self.refresh_remote()

    def on_connect_failed(self, exc: Exception) -> None:
        self.btn_connect.configure(state="normal")
        self.btn_disconnect.configure(state="disabled")
        self.client = None
        if isinstance(exc, ServerError):
            self.log(f"登录失败：{exc.code} - {exc.message}")
            messagebox.showerror("登录失败", exc.message)
        else:
            self.log(f"连接失败：{exc!r}")
            messagebox.showerror("连接失败", str(exc))

    def on_disconnect(self) -> None:
        if not self.client:
            return
        client = self.client
        self.client = None
        self.run_async(client.close(), lambda _: self.log("连接已关闭"))
        self.btn_connect.configure(state="normal")
        self.btn_disconnect.configure(state="disabled")
        self.tls_var.set("未连接")
        self.status_var.set("未连接")
        self.remote_tree.delete(*self.remote_tree.get_children())

    # ------------------------------------------------------------ local files
    def refresh_local(self) -> None:
        self.local_path_var.set(str(self.local_path))
        tree = self.local_tree
        tree.delete(*tree.get_children())
        try:
            entries = sorted(self.local_path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError as exc:
            self.log(f"无法读取目录：{exc}")
            return
        for path in entries:
            if path.name.startswith("."):
                continue
            stat = path.stat()
            tree.insert("", "end", iid=str(path), values=(
                ("▸ " if path.is_dir() else "  ") + path.name,
                "" if path.is_dir() else self.fmt_size(stat.st_size),
                time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
            ), tags=("dir",) if path.is_dir() else ())

    def on_local_open(self, _event=None) -> None:
        sel = self.local_tree.focus()
        if not sel:
            return
        path = Path(sel)
        if path.is_dir():
            self.local_path = path
            self.refresh_local()

    def local_up(self) -> None:
        self.local_path = self.local_path.parent
        self.refresh_local()

    # ----------------------------------------------------------- remote files
    def refresh_remote(self) -> None:
        if not self.client:
            return
        path = self.remote_path
        self.remote_path_var.set("/" if path == "." else path)

        def done(body: dict) -> None:
            tree = self.remote_tree
            tree.delete(*tree.get_children())
            for item in body.get("entries", []):
                name = item["name"]
                tree.insert("", "end", iid=name, values=(
                    ("▸ " if item["type"] == "dir" else "  ") + name,
                    "" if item["type"] == "dir" else self.fmt_size(item["size"]),
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(item["mtime"])),
                ), tags=("dir",) if item["type"] == "dir" else ())

        self.run_async(self.client.list_dir(path), done)

    def on_remote_open(self, _event=None) -> None:
        sel = self.remote_tree.focus()
        if not sel:
            return
        values = self.remote_tree.item(sel, "values")
        if values and str(values[0]).startswith("▸"):
            self.remote_path = self.join_remote(self.remote_path, sel)
            self.refresh_remote()

    def remote_up(self) -> None:
        if self.remote_path in (".", ""):
            return
        parts = self.remote_path.split("/")
        self.remote_path = "/".join(parts[:-1]) or "."
        self.refresh_remote()

    @staticmethod
    def join_remote(base: str, name: str) -> str:
        return name if base in (".", "") else f"{base}/{name}"

    def on_mkdir(self) -> None:
        if not self.client:
            return
        name = simpledialog.askstring("新建目录", "目录名称：", parent=self)
        if not name:
            return
        target = self.join_remote(self.remote_path, name.strip())
        self.run_async(self.client.mkdir(target),
                       lambda _: (self.log(f"已创建目录 {target}"), self.refresh_remote()))

    def on_delete(self) -> None:
        if not self.client:
            return
        selection = self.remote_tree.selection()
        if not selection:
            return
        if not messagebox.askyesno("确认删除", f"删除远程条目：{', '.join(selection)}？"):
            return
        for name in selection:
            self.run_async(self.client.delete(self.join_remote(self.remote_path, name)))
        self.after(600, self.refresh_remote)

    # --------------------------------------------------------------- transfers
    def _new_transfer(self, name: str, direction: str, local: str, remote: str, size: int) -> Transfer:
        self._tid += 1
        tr = Transfer(tid=self._tid, name=name, direction=direction, local=local,
                      remote=remote, size=size, state="运行中")
        self.transfers[tr.tid] = tr
        self.tr_tree.insert("", "end", iid=str(tr.tid), values=(
            name, direction, self.fmt_size(size), "0%", "-", "运行中"))
        return tr

    def on_upload(self) -> None:
        if not self.client:
            return
        selection = self.local_tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先在左侧选择要上传的文件")
            return
        for item in selection:
            path = Path(item)
            if path.is_dir():
                continue
            remote = self.join_remote(self.remote_path, path.name)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            tr = self._new_transfer(path.name, "上传", str(path), remote, size)
            self._start_upload(tr)

    def _start_upload(self, tr: Transfer) -> None:
        assert self.client is not None
        control = TransferControl()

        def progress(done: int, total: int) -> None:
            self.events.put(("progress", tr.tid, done, total))

        def finished(body: dict) -> None:
            self.events.put(("done", tr.tid, body))

        def failed(exc: Exception) -> None:
            self.events.put(("failed", tr.tid, exc))

        tr.control = control
        tr.state = "运行中"
        tr.offset = 0
        self.run_async(self.client.upload(tr.local, tr.remote, control, progress),
                       finished, failed)

    def on_download(self) -> None:
        if not self.client:
            return
        selection = [i for i in self.remote_tree.selection()
                     if not str(self.remote_tree.item(i, "values")[0]).startswith("▸")]
        if not selection:
            messagebox.showinfo("提示", "请先在右侧选择要下载的文件")
            return
        remote_dir = self.remote_path
        for name in selection:
            remote = self.join_remote(remote_dir, name)
            local = str(self.local_path / name)
            tr = self._new_transfer(name, "下载", local, remote, 0)
            self._start_download(tr)

    def _start_download(self, tr: Transfer) -> None:
        assert self.client is not None
        control = TransferControl()

        def progress(done: int, total: int) -> None:
            self.events.put(("progress", tr.tid, done, total))

        def finished(body: dict) -> None:
            self.events.put(("done", tr.tid, body))

        def failed(exc: Exception) -> None:
            self.events.put(("failed", tr.tid, exc))

        tr.control = control
        tr.state = "运行中"
        self.run_async(self.client.download(tr.remote, tr.local, control, progress),
                       finished, failed)

    def _selected_transfer(self) -> Transfer | None:
        sel = self.tr_tree.selection()
        if not sel:
            return None
        return self.transfers.get(int(sel[0]))

    def on_pause(self) -> None:
        tr = self._selected_transfer()
        if tr and tr.state == "运行中":
            tr.control.pause()
            tr.state = "暂停中"
            self.log(f"请求暂停：{tr.name}")

    def on_resume(self) -> None:
        tr = self._selected_transfer()
        if not tr:
            return
        if tr.direction == "上传":
            tr.offset = tr.done
            self._start_upload(tr)
            self.log(f"断点续传：{tr.name} 从 {self.fmt_size(tr.done)} 继续上传")
        else:
            self._start_download(tr)
            self.log(f"断点续传：{tr.name} 从本地 .part 继续下载")

    def on_cancel(self) -> None:
        tr = self._selected_transfer()
        if tr and tr.state in ("运行中", "暂停中"):
            tr.control.cancel()
            tr.state = "取消中"

    def on_clear(self) -> None:
        for tid, tr in list(self.transfers.items()):
            if tr.state in ("已完成", "失败", "已取消", "已暂停"):
                self.tr_tree.delete(str(tid))
                self.transfers.pop(tid, None)

    # -------------------------------------------------------------- event loop
    def _pump(self) -> None:
        try:
            while True:
                kind, *rest = self.events.get_nowait()
                if kind == "progress":
                    tid, done, total = rest
                    tr = self.transfers.get(tid)
                    if tr:
                        tr.done, tr.size = done, total
                elif kind == "done":
                    tid, body = rest
                    tr = self.transfers.get(tid)
                    if tr:
                        tr.done = tr.size = int(body.get("size", tr.size))
                        tr.state = "已完成"
                        self.log(f"完成：{tr.name}（{self.fmt_size(tr.size)}，"
                                 f"{body.get('sha256', '')[:12]}…）")
                elif kind == "failed":
                    tid, exc = rest
                    tr = self.transfers.get(tid)
                    if tr:
                        if isinstance(exc, TransferAborted):
                            tr.state = "已暂停" if tr.control.paused else "已取消"
                            self.log(f"{tr.state}：{tr.name} @ {self.fmt_size(tr.done)}")
                        elif isinstance(exc, ServerError):
                            tr.state = "失败"
                            tr.note = exc.message
                            self.log(f"失败：{tr.name} - {exc.code} {exc.message}")
                        else:
                            tr.state = "失败"
                            tr.note = str(exc)
                            self.log(f"失败：{tr.name} - {exc!r}")
                elif kind == "ok":
                    callback, result = rest
                    callback(result)
                elif kind == "error":
                    callback, exc = rest
                    callback(exc)
        except queue.Empty:
            pass
        self._render_transfers()
        self.after(200, self._pump)

    def _render_transfers(self) -> None:
        active = 0
        for tid, tr in self.transfers.items():
            if tr.state == "运行中":
                active += 1
            pct = (tr.done / tr.size * 100) if tr.size else (100 if tr.state == "已完成" else 0)
            filled = int(pct // 4)
            bar = "▰" * filled + "▱" * (25 - filled)
            speed = ""
            if tr.state == "运行中":
                now = time.monotonic()
                gap = now - tr.last_ts
                if gap >= 0.5:
                    tr.speed = (tr.done - tr.last_bytes) / gap
                    tr.last_bytes, tr.last_ts = tr.done, now
                speed = f"{self.fmt_size(tr.speed)}/s" if tr.speed else "-"
            self.tr_tree.item(str(tid), values=(
                tr.name, tr.direction, self.fmt_size(tr.size),
                f"{bar} {pct:5.1f}%", speed, tr.state + (f"（{tr.note}）" if tr.note else "")))
        self.summary_var.set(f"{active} 个活动传输" if active else "无活动传输")

    def _tick(self) -> None:
        if self.client and not self.client.closed:
            self.stream_var.set(f"RTT {self.client.rtt_ms:.0f} ms · 心跳 {self.client.keepalive:.0f}s")
        self.after(1000, self._tick)

    def on_close(self) -> None:
        try:
            if self.client:
                self.worker.submit(self.client.close())
            self.worker.stop()
        finally:
            self.destroy()


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
