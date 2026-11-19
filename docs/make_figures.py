"""Generate the diagrams embedded in the lab report.

    python docs/make_figures.py

Everything is drawn with matplotlib primitives so the figures stay in sync with
the design described in the text (no external diagram tool needed).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parent / "figures"
OUT.mkdir(parents=True, exist_ok=True)

INK = "#1f2328"
MUTED = "#5f6368"
LINE = "#9aa0a6"
BLUE = "#dbeafe"
BLUE_L = "#eff6ff"
GREEN = "#dcfce7"
AMBER = "#fef3c7"
RED = "#fee2e2"
GREY = "#f3f4f6"


def box(ax, x, y, w, h, text, fc=BLUE, fs=10, sub=None, ec="#93a4b8", bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.02",
                                linewidth=1.0, edgecolor=ec, facecolor=fc))
    if sub:
        ax.text(x + w / 2, y + h * 0.62, text, ha="center", va="center",
                fontsize=fs, color=INK, fontweight="bold" if bold else "normal")
        ax.text(x + w / 2, y + h * 0.30, sub, ha="center", va="center", fontsize=fs - 1.5, color=MUTED)
    else:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, color=INK, fontweight="bold" if bold else "normal",
                linespacing=1.5)


def arrow(ax, p1, p2, label=None, style="-|>", ls="-", color=INK, fs=9, offset=0.012, dashed=False):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle=style, mutation_scale=12,
                                 linewidth=1.1, color=color,
                                 linestyle="--" if dashed else ls,
                                 shrinkA=0, shrinkB=0))
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        ax.text(mx, my + offset, label, ha="center", va="bottom", fontsize=fs, color=MUTED)


# --------------------------------------------------------------------- 1. 架构
def fig_architecture():
    fig, ax = plt.subplots(figsize=(9.4, 6.0))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.add_patch(FancyBboxPatch((0.02, 0.10), 0.40, 0.80, boxstyle="round,pad=0.01,rounding_size=0.03",
                                facecolor=GREY, edgecolor="#d0d5dd"))
    ax.text(0.05, 0.855, "客户端进程（Windows / Python 3.13 + Tk）", fontsize=9.6, color=INK)
    box(ax, 0.05, 0.62, 0.34, 0.16, "GUI 层", sub="登录 · 双栏浏览 · 传输队列 · 日志", fc="#ffffff")
    box(ax, 0.05, 0.42, 0.34, 0.16, "传输层", sub="AsyncWorker 事件循环 · 多流复用 · 心跳", fc=BLUE)
    box(ax, 0.05, 0.22, 0.34, 0.16, "SFAP/1 编解码", sub="24B 报头 + JSON 元数据 + 二进制载荷", fc=BLUE_L)
    box(ax, 0.05, 0.13, 0.34, 0.06, "证书库（CA / 客户端证书 / 私钥）", fc="#ffffff", fs=9)

    ax.add_patch(FancyBboxPatch((0.46, 0.36), 0.08, 0.30, boxstyle="round,pad=0.01,rounding_size=0.03",
                                facecolor=AMBER, edgecolor="#d6b26a"))
    ax.text(0.50, 0.51, "TLS 1.3\n双向认证", ha="center", va="center", fontsize=9.5, color=INK)

    ax.add_patch(FancyBboxPatch((0.58, 0.10), 0.40, 0.80, boxstyle="round,pad=0.01,rounding_size=0.03",
                                facecolor=GREY, edgecolor="#d0d5dd"))
    ax.text(0.61, 0.855, "服务端进程（asyncio TLS Server）", fontsize=9.6, color=INK)
    box(ax, 0.61, 0.66, 0.34, 0.12, "会话层 Session", sub="认证状态机 · 心跳 · 空闲超时 · 流调度", fc=BLUE)
    box(ax, 0.61, 0.50, 0.16, 0.12, "上传流", sub=".part + SHA-256", fc=BLUE_L, fs=9)
    box(ax, 0.79, 0.50, 0.16, 0.12, "下载流", sub="分块 + 令牌桶", fc=BLUE_L, fs=9)
    box(ax, 0.61, 0.33, 0.34, 0.12, "安全控制面", sub="PeerGuard · 登录锁定 · 报文限速 · 审计", fc=RED, fs=9)
    box(ax, 0.61, 0.17, 0.34, 0.11, "数据面", sub="用户沙箱 · ACL 目录 · SQLite 用户库", fc=GREEN, fs=9)
    box(ax, 0.61, 0.11, 0.34, 0.045, "run/data/<user>/ …", fc="#ffffff", fs=8.5)

    arrow(ax, (0.39, 0.50), (0.46, 0.50), "", style="-|>")
    arrow(ax, (0.54, 0.50), (0.61, 0.50), "", style="-|>")
    ax.text(0.50, 0.72, "SFAP/1 over TLS/TCP", ha="center", va="bottom", fontsize=8.8, color=MUTED)

    ax.text(0.5, 0.045, "图 1  系统总体架构：客户端负责交互与协议编解码，服务端负责认证、沙箱、限速与持久化",
            ha="center", fontsize=9, color=MUTED)
    fig.savefig(OUT / "fig_architecture.png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ------------------------------------------------------------------ 2. 报头布局
def fig_header():
    fields = [
        ("magic", 2, "#dbeafe"),
        ("ver", 1, "#eff6ff"),
        ("type", 1, "#eff6ff"),
        ("flags", 1, "#fef3c7"),
        ("rsvd", 1, "#f9fafb"),
        ("stream_id", 4, "#dcfce7"),
        ("sequence", 4, "#dcfce7"),
        ("body_len", 4, "#f3e8ff"),
        ("payload_len", 4, "#f3e8ff"),
        ("CRC16", 2, "#fee2e2"),
    ]
    desc = {
        "magic": "0x53 0x46（'SF'），TCP 层即可剔除非法连接",
        "ver": "协议版本，当前为 1",
        "type": "消息类型，见 3.3 节消息表",
        "flags": "LAST / RESUME / ACKREQ / ERROR",
        "rsvd": "保留字节，使报头 4 字节对齐",
        "stream_id": "同一条连接内多路复用的流标识",
        "sequence": "流内帧序号，乱序即中止该流",
        "body_len": "JSON 控制元数据长度，上限 16 KiB",
        "payload_len": "二进制载荷长度，上限 1 MiB",
        "CRC16": "CRC-16/CCITT，覆盖前 22 字节",
    }
    total = sum(f[1] for f in fields)
    fig, ax = plt.subplots(figsize=(9.6, 4.9))
    ax.set_xlim(-0.5, total + 0.5)
    ax.set_ylim(-0.2, 1.55)
    ax.axis("off")

    x = 0
    for index, (name, width, color) in enumerate(fields):
        ax.add_patch(Rectangle((x, 0.95), width, 0.34, facecolor=color,
                               edgecolor="#6b7280", linewidth=1.0))
        ax.text(x + width / 2, 1.12, name, ha="center", va="center", fontsize=7.4, color=INK)
        ax.text(x, 1.34, str(x), ha="center", va="bottom", fontsize=7, color=MUTED)
        seg = total / 24 * width
        ax.text(x + seg / 2, 0.90, f"{width}B", ha="center", va="top", fontsize=6.6, color=MUTED)
        x += width
    ax.text(total, 1.34, "24", ha="center", va="bottom", fontsize=7, color=MUTED)
    ax.annotate("", xy=(0, 1.47), xytext=(total, 1.47),
                arrowprops=dict(arrowstyle="<|-|>", color=LINE, lw=0.9))
    ax.text(total / 2, 1.50, "固定 24 字节报头（大端序，单位：字节）", ha="center", va="bottom",
            fontsize=8.6, color=MUTED)

    ax.plot([0, total], [0.83, 0.83], color="#d0d5dd", lw=1.0)
    cols, rows = 2, 5
    for index, (name, width, _c) in enumerate(fields):
        col, row = index // rows, index % rows
        bx = -0.3 + col * (total / 2 + 0.3)
        by = 0.72 - row * 0.17
        ax.text(bx, by, f"{name}", ha="left", va="center", fontsize=8.4,
                color=INK, fontweight="bold")
        ax.text(bx + 2.9, by, desc[name], ha="left", va="center", fontsize=8.0, color=MUTED)
    fig.savefig(OUT / "fig_header.png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ------------------------------------------------------------------- 3. 时序图
def sequence(title, actors, steps, path, height=7.2, note=None):
    fig, ax = plt.subplots(figsize=(9.2, height))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    n = len(actors)
    xs = {name: 0.08 + i * (0.84 / (n - 1)) for i, name in enumerate(actors)}
    for name, x in xs.items():
        ax.add_patch(FancyBboxPatch((x - 0.075, 0.935), 0.15, 0.055,
                                    boxstyle="round,pad=0.006,rounding_size=0.012",
                                    facecolor=BLUE, edgecolor="#93a4b8", linewidth=1.0))
        ax.text(x, 0.9625, name, ha="center", va="center", fontsize=9.2, color=INK)
        ax.plot([x, x], [0.05, 0.935], color=LINE, lw=0.9, ls=(0, (4, 3)))

    top, bottom = 0.86, 0.10
    step = (top - bottom) / max(len(steps), 1)
    y = top
    for item in steps:
        src, dst, label, kind = item[0], item[1], item[2], item[3] if len(item) > 3 else "solid"
        y -= step * 0.92
        if src == dst:
            ax.add_patch(FancyArrowPatch((xs[src], y), (xs[src] + 0.055, y),
                                         arrowstyle="-", lw=1.0, color=LINE))
            ax.add_patch(FancyArrowPatch((xs[src] + 0.055, y), (xs[src] + 0.055, y - step * 0.35),
                                         arrowstyle="-", lw=1.0, color=LINE))
            ax.add_patch(FancyArrowPatch((xs[src] + 0.055, y - step * 0.35), (xs[src], y - step * 0.35),
                                         arrowstyle="-|>", mutation_scale=11, lw=1.0, color=INK))
            ax.text(xs[src] + 0.065, y - step * 0.12, label, ha="left", va="center",
                    fontsize=8.8, color=MUTED)
            y -= step * 0.35
            continue
        color = "#a32d2d" if kind == "error" else INK
        ax.add_patch(FancyArrowPatch((xs[src], y), (xs[dst], y), arrowstyle="-|>",
                                     mutation_scale=12, lw=1.2, color=color,
                                     linestyle="--" if kind == "dashed" else "-"))
        ax.text((xs[src] + xs[dst]) / 2, y + 0.012, label, ha="center", va="bottom",
                fontsize=8.6, color=color)
    if note:
        # Captions live in the .docx (and carry the figure number), so the image
        # itself stays clean unless an explicit note is requested.
        ax.text(0.5, 0.03, note, ha="center", fontsize=8.0, color=MUTED)
    fig.savefig(OUT / path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig_login():
    sequence(
        "登录认证",
        ["客户端", "服务端", "SQLite", "文件系统"],
        [
            ("客户端", "服务端", "TCP 连接 + TLS ClientHello（携带客户端证书）"),
            ("服务端", "客户端", "TLS ServerHello + 证书链，校验证书 CN"),
            ("客户端", "服务端", "LOGIN_REQ{user, pass}"),
            ("服务端", "SQLite", "SELECT salt,pwhash FROM users WHERE name=?", "dashed"),
            ("SQLite", "服务端", "salt + scrypt(pass, salt)", "dashed"),
            ("服务端", "服务端", "常数时间比较 + CN 与账户绑定校验"),
            ("服务端", "客户端", "LOGIN_RESP{role, keepalive,\nrate_bps, window}"),
            ("服务端", "文件系统", "创建/检查 run/data/<user>/ 沙箱"),
            ("客户端", "客户端", "启动心跳：每 20 s PING / PONG", "dashed"),
        ],
        "fig_login_seq.png",
        height=6.6,
    )


def fig_upload():
    sequence(
        "上传与断点续传",
        ["客户端", "服务端", "磁盘"],
        [
            ("客户端", "服务端", "UPLOAD_REQ{path, size,\nsha256, resume=true}"),
            ("服务端", "磁盘", "读取 .part 长度与前缀 SHA-256", "dashed"),
            ("服务端", "客户端", "UPLOAD_RESP{offset=已写入字节数}"),
            ("客户端", "客户端", "本地文件 seek(offset)，续算摘要"),
            ("客户端", "服务端", "DATA[0..n]{stream, seq, 256 KiB}"),
            ("服务端", "磁盘", "写入 .part，累加摘要"),
            ("服务端", "客户端", "DATA_ACK{acked}（每 1 MiB）"),
            ("客户端", "服务端", "UPLOAD_END{sha256}"),
            ("服务端", "磁盘", "fsync + 校验 + 原子 rename"),
            ("服务端", "客户端", "UPLOAD_RESP_END{ok, rate_mbps}"),
        ],
        "fig_upload_seq.png",
        height=7.2,
    )


def fig_download():
    sequence(
        "下载与暂停恢复",
        ["客户端", "服务端", "磁盘"],
        [
            ("客户端", "服务端", "DOWNLOAD_REQ{path, offset=0}"),
            ("服务端", "磁盘", "打开文件，计算前缀摘要"),
            ("服务端", "客户端", "DOWNLOAD_RESP{size, chunk}"),
            ("服务端", "客户端", "DATA{seq, payload}（按角色限速）"),
            ("客户端", "磁盘", "追加写入 <file>.part"),
            ("服务端", "客户端", "DATA{eof, sha256}"),
            ("客户端", "客户端", "校验 SHA-256 后原子改名为目标文件"),
            ("客户端", "服务端", "CANCEL{stream}（用户点“暂停”时）", "dashed"),
            ("服务端", "客户端", "DATA{cancelled, offset}"),
            ("客户端", "服务端", "DOWNLOAD_REQ{offset}（点“继续”）"),
        ],
        "fig_download_seq.png",
        height=7.4,
    )


# ------------------------------------------------------------------ 4. 状态机
def fig_state():
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    states = [
        (0.03, "NEW\n握手", GREY),
        (0.21, "TLS_OK\n已双向认证", BLUE_L),
        (0.39, "AUTHENTICATING\n校验口令/证书", AMBER),
        (0.57, "READY\n空闲 · 心跳", GREEN),
        (0.75, "TRANSFERRING\n多流并行", BLUE),
        (0.90, "CLOSED\n释放资源", RED),
    ]
    w = 0.14
    for x, label, color in states:
        ax.add_patch(FancyBboxPatch((x, 0.45), w, 0.22, boxstyle="round,pad=0.008,rounding_size=0.02",
                                    facecolor=color, edgecolor="#8c9bab", linewidth=1.0))
        ax.text(x + w / 2, 0.56, label, ha="center", va="center", fontsize=8.6, color=INK)

    for i in range(len(states) - 1):
        x1 = states[i][0] + w
        x2 = states[i + 1][0]
        arrow(ax, (x1 + 0.004, 0.56), (x2 - 0.004, 0.56), "", fs=8)

    arrow(ax, (0.64, 0.45), (0.64, 0.30), "登录失败 / 3 次重试", fs=8, color="#a32d2d")
    ax.plot([0.64, 0.97], [0.30, 0.30], color="#a32d2d", lw=1.1, ls="--")
    arrow(ax, (0.97, 0.30), (0.97, 0.45), "", color="#a32d2d")

    arrow(ax, (0.82, 0.45), (0.82, 0.75), "传输结束", fs=8, color="#0f6e56")
    ax.plot([0.82, 0.64], [0.78, 0.78], color="#0f6e56", lw=1.1, ls="--")
    arrow(ax, (0.64, 0.78), (0.64, 0.67), "", color="#0f6e56")

    arrow(ax, (0.61, 0.45), (0.61, 0.13), "空闲超时 75 s / BYE / 洪水检测", fs=8, color="#a32d2d")
    ax.plot([0.61, 0.97], [0.13, 0.13], color="#a32d2d", lw=1.1, ls="--")
    arrow(ax, (0.97, 0.13), (0.97, 0.45), "", color="#a32d2d")

    ax.text(0.5, 0.02, "图 6  服务端会话状态机：任何状态异常都收敛到 CLOSED，并由 finally 释放连接配额",
            ha="center", fontsize=9, color=MUTED)
    fig.savefig(OUT / "fig_state.png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    fig_architecture()
    fig_header()
    fig_login()
    fig_upload()
    fig_download()
    from PIL import Image
    for f in sorted(OUT.glob("fig_*.png")):
        # Word renders RGBA PNGs badly (transparent areas turn green in PDF export),
        # so flatten every figure to RGB before it is embedded in the report.
        Image.open(f).convert("RGB").save(f, optimize=True)
        print("wrote", f.name, f.stat().st_size // 1024, "KiB")
