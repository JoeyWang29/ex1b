#!/usr/bin/env python3
"""Generate docs/report.docx (the deliverable lab report).

    python docs/make_report.py
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
FIGDIR = ROOT / "docs" / "figures"
OUT = ROOT / "docs" / "report.docx"

INK = RGBColor(0x1F, 0x23, 0x28)
GREY = RGBColor(0x5F, 0x66, 0x6E)
ACCENT = RGBColor(0x18, 0x5F, 0xA5)

doc = Document()

# --------------------------------------------------------------------- page
section = doc.sections[0]
section.page_width = Cm(21.0)
section.page_height = Cm(29.7)
section.top_margin = Cm(2.4)
section.bottom_margin = Cm(2.2)
section.left_margin = Cm(2.4)
section.right_margin = Cm(2.2)
section.different_first_page_header_footer = True


def cn(run, font="宋体", size=10.5, bold=False, color=INK):
    run.font.name = "Times New Roman"
    run.font.size = Pt(size)
    run.bold = bold
    run.font.color.rgb = color
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), font)


def style_base() -> None:
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    pf = normal.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = 1.45
    pf.space_before = Pt(0)
    pf.space_after = Pt(3)

    for name, size in (("Heading 1", 15), ("Heading 2", 12.5), ("Heading 3", 11)):
        st = doc.styles[name]
        st.font.name = "Times New Roman"
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = INK
        st.element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
        st.paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10)
        st.paragraph_format.space_after = Pt(6)
        st.paragraph_format.keep_with_next = True


style_base()


def H1(text: str) -> None:
    doc.add_heading(text, level=1)


def H2(text: str) -> None:
    doc.add_heading(text, level=2)


def P(text: str, indent: bool = True, size: float = 10.5, color=INK, after: float = 3,
      align=None) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    if indent:
        p.paragraph_format.first_line_indent = Pt(size * 2)
    if align is not None:
        p.alignment = align
    run = p.add_run(text)
    cn(run, size=size, color=color)


def BULLET(text: str, size: float = 10.5) -> None:
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.left_indent = Pt(18)
    run = p.add_run(text)
    cn(run, size=size)


def CODE(text: str) -> None:
    for line in text.rstrip("\n").split("\n"):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.left_indent = Pt(12)
        run = p.add_run(line if line else " ")
        run.font.name = "Consolas"
        run.font.size = Pt(8.5)
        run.font.color.rgb = RGBColor(0x2B, 0x2F, 0x36)
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), "F4F6F8")
        p._p.get_or_add_pPr().append(shd)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def shade(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def CAPTION(text: str, kind: str = "图") -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(10)
    run = p.add_run(text)
    cn(run, size=9, color=GREY)


def TABLE(headers: list[str], rows: list[list[str]], widths: list[float],
          caption: str | None = None, size: float = 8.8, header_fill: str = "E8EDF4") -> None:
    if caption:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(caption)
        cn(run, font="黑体", size=9.5, bold=True)
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for index, head in enumerate(headers):
        cell = table.rows[0].cells[index]
        cell.width = Cm(widths[index])
        cell.text = ""
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_after = Pt(1)
        run = para.add_run(head)
        cn(run, font="黑体", size=size, bold=True)
        shade(cell, header_fill)
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].width = Cm(widths[index])
            cells[index].text = ""
            para = cells[index].paragraphs[0]
            para.paragraph_format.space_after = Pt(1)
            para.paragraph_format.line_spacing = 1.15
            run = para.add_run(str(value))
            cn(run, size=size)
    # repeat the header row on page breaks and never split a row in half
    head_tr = table.rows[0]._tr
    tr_pr = head_tr.get_or_add_trPr()
    flag = OxmlElement("w:tblHeader")
    flag.set(qn("w:val"), "true")
    tr_pr.append(flag)
    for index, row in enumerate(table.rows):
        prop = row._tr.get_or_add_trPr()
        prop.append(OxmlElement("w:cantSplit"))
        if index < len(table.rows) - 1:
            for cell in row.cells:
                for para in cell.paragraphs:
                    para.paragraph_format.keep_with_next = True
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def FIG(name: str, caption: str, width: float = 16.2) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    p.add_run().add_picture(str(FIGDIR / name), width=Cm(width))
    CAPTION(caption)


# -------------------------------------------------------------------- cover
def cover() -> None:
    for _ in range(3):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("《软件与系统安全》实验 1B 报告")
    cn(run, font="黑体", size=15, color=GREY)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(10)
    run = p.add_run("安全文件传输软件")
    cn(run, font="黑体", size=30, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("SecureFile：自定义应用层协议 SFAP/1 的设计与实现")
    cn(run, font="黑体", size=13, color=ACCENT)

    for _ in range(5):
        doc.add_paragraph()

    rows = [("姓    名", "王恩泽"), ("学    号", "202628007329016"), ("学    校", "中国科学院大学"),
            ("院    系", "计算机科学与技术学院"), ("课程教师", "刘  鹏"),
            ("提交日期", "2026 年 11 月 24 日")]
    table = doc.add_table(rows=0, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for key, value in rows:
        cells = table.add_row().cells
        cells[0].width = Cm(3.6)
        cells[1].width = Cm(7.0)
        para = cells[0].paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run = para.add_run(key + "：")
        cn(run, font="黑体", size=11)
        para = cells[1].paragraphs[0]
        run = para.add_run(value)
        cn(run, size=11)

    for _ in range(4):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("源代码仓库：https://github.com/JoeyWang29/ex1b")
    cn(run, size=9, color=GREY)
    doc.add_page_break()


# ------------------------------------------------------------------- 1 概览
def part_one() -> None:
    H1("1  实验概述")
    P("本实验实现了一套完整的安全文件传输系统 SecureFile：客户端为 Windows 桌面图形程序，"
      "服务端为多用户并发的守护进程，两端通过自定义的应用层协议 SFAP/1（Secure File Application "
      "Protocol）通信，协议报文承载在 TLS 1.3 双向认证的通道上。系统支持多用户并发、目录浏览、"
      "上传下载、断点续传、按角色限速、服务端目录沙箱与审计，并通过一套 19 项用例的自动化测试"
      "验证了功能正确性与安全性。")

    H2("1.1  课程要求与完成情况")
    P("表 1 逐条对照课件中实验 1B 的要求与实现位置，便于批阅时定位证据。", indent=False)
    TABLE(
        ["课程要求", "本实现的做法", "证据位置"],
        [
            ["实现一种简单但安全的文件传输协议", "24 字节定长报头 + JSON 控制体 + 二进制载荷；"
                                                 "流号复用、序号、窗口确认、CRC16 校验",
             "3 节；protocol.py"],
            ["多用户并发访问", "asyncio 单线程事件循环 + 每连接会话任务；单连接内 4 条流复用",
             "5.1 节；server.py"],
            ["文件可完整传输", "分块 256 KiB、累计 ACK、SHA-256 端到端校验、.part 原子改名",
             "3.7 节；6.2 节用例"],
            ["抵御中间人攻击", "私有 CA 签发服务端/客户端证书，TLS 1.3 双向认证，CN 与账户绑定",
             "4.2、4.3 节"],
            ["抵御 DDoS", "连接配额、握手/空闲超时、控制帧洪泛检测、登录锁定、令牌桶限速、配额",
             "4.6 节"],
            ["抵御 SQL 注入", "全部语句参数化；错误口令与注入载荷均被拒绝", "4.5 节；用例 5"],
            ["长连接 + keepalive", "20 s 双向心跳，75 s 空闲超时，守护任务维持连接直至手动关闭",
             "3.5 节；用例 18"],
            ["报告写明协议设计（时序图/报头图）", "图 2 报头字段图；图 3–5 登录/上传/下载时序图",
             "3 节"],
            ["服务端可读写目录以脚本明确体现", "setfacl 与 icacls 两套 ACL 脚本，附 systemd 加固片段",
             "4.4 节；scripts/acl_server.*"],
        ],
        widths=[5.2, 8.8, 3.4],
        caption="表 1  课程要求与实现对照",
    )

    H2("1.2  交付物与运行方式")
    P("交付物按课件要求组织：源码目录、演示视频与报告；代码托管在 GitHub（https://github.com/JoeyWang29/ex1b），"
      "保留了按模块划分的完整提交记录（协议、服务端、客户端、安全脚本、测试与文档）。"
      "工程可直接在 Windows 上以 Python 3.13 运行，无第三方运行时依赖（仅 GUI 使用标准库 tkinter，"
      "绘图脚本使用 matplotlib）。")
    CODE("""securefile/
├── protocol.py        SFAP/1 帧编解码、消息类型、CRC16
├── server.py          TLS 服务端、会话状态机、上传/下载流、限速与审计
├── auth.py            SQLite 用户库（scrypt 口令、证书 CN 绑定、参数化查询）
├── sandbox.py         路径规范化与沙箱逃逸防护
├── ratelimit.py       令牌桶、单 IP 连接配额、登录失败锁定
├── client_core.py     TLS 客户端、多流复用、断点续传（后台事件循环）
├── client_gui.py      Tk 图形客户端：登录、双栏浏览、传输队列、日志
├── config.server.json 服务端配置（端口、证书、配额、限速）
├── scripts/           gen_certs.sh(.ps1) / acl_server.sh(.ps1)
├── tests/             e2e.py（19 项用例）、benchmark.py（限速实测）
└── docs/              协议说明、图表脚本、本报告""")
    P("启动顺序：生成证书 → 初始化用户 → 启动服务端 → 启动图形客户端。完整命令见第 8 节。")


# ------------------------------------------------------------------- 2 设计
def part_two() -> None:
    H1("2  系统设计")
    H2("2.1  总体架构")
    P("系统分为客户端与服务端两个进程，中间是 TLS 1.3 通道。客户端内部又分为图形层、传输层与协议层："
      "图形层只负责交互，传输层在自己的后台线程里跑一个 asyncio 事件循环，协议层负责把一次业务操作"
      "拆成若干帧。服务端以单进程 asyncio 承载全部连接，每条连接是一个会话任务，会话内部再按流号"
      "调度上传与下载。")
    FIG("fig_architecture.png", "图 1  系统总体架构")
    P("把 GUI 与网络 I/O 分到不同线程，是为了避免 Tk 的事件循环被磁盘或网络阻塞；而服务端坚持单线程"
      "事件循环，则避免了多线程共享会话状态时的加锁成本——真正需要串行化的只有帧写入，这一点由"
      "写锁保证。")

    H2("2.2  技术选型")
    P("课件给出了 WinForms/WPF、Web（Java/Node + Vue + 容器）等多条路线。本实现选择 Python + asyncio + Tk，"
      "理由是对比之后的结果，而不是熟悉程度：")
    TABLE(
        ["方案", "优势", "代价", "结论"],
        [
            ["C# WinForms/WPF", "原生 Windows 体验，课件推荐", "需要 Visual Studio 2025；协议层与 UI 强耦合，"
                                                                    "TLS 双向认证配置繁琐", "未采用"],
            ["Java/Node + Web", "生态成熟、可容器部署", "浏览器会强制 HTTPS/证书信任流程，自定义长连接需绕过"
                                                        "HTTP 语义；演示时还要装运行时", "未采用"],
            ["Python + asyncio + Tk", "标准库自带 TLS/SQLite/scrypt；单文件即可跑；协议与 UI 解耦",
             "GUI 观感朴素；打包体积较大", "采用"],
        ],
        widths=[3.6, 5.2, 6.2, 2.2],
        caption="表 2  技术路线对比",
    )
    P("选型的核心判断是：本实验的评分点在“协议设计”与“安全性”，而不是界面控件。Python 让协议层可以写得"
      "足够薄、足够可读，Tk 又足以表达文件浏览、进度条与传输队列这些必要交互，因此把复杂度留给了协议本身。")

    H2("2.3  目录与模块职责")
    TABLE(
        ["模块", "行数", "职责", "关键设计"],
        [
            ["protocol.py", "246", "帧编解码、类型与错误码", "定长报头 + CRC16；limit 检查前置"],
            ["server.py", "735", "会话、上传/下载、调度、审计", "每连接一个任务；写锁串行化帧"],
            ["auth.py", "174", "用户库与口令校验", "scrypt(n=2^14)；常数时间比较"],
            ["sandbox.py", "69", "路径规范化与越权检测", "realpath + commonpath 双重校验"],
            ["ratelimit.py", "99", "令牌桶与连接配额", "协程安全；按 IP 独立计数"],
            ["client_core.py", "393", "客户端传输层", "后台事件循环；4 MiB 发送窗口"],
            ["client_gui.py", "652", "图形界面与传输队列", "事件队列回传进度，避免跨线程操作 Tk"],
        ],
        widths=[3.2, 1.4, 5.6, 7.0],
        caption="表 3  模块职责（合计约 2 400 行，不含测试）",
    )


# ------------------------------------------------------------------ 3 协议
def part_three() -> None:
    H1("3  应用层协议 SFAP/1")
    H2("3.1  设计原则")
    P("协议要解决三件事：把字节流切成一帧一帧、在同一条连接上区分不同的传输、以及让业务字段可以演进。"
      "对应的三条原则是：")
    BULLET("定长报头承载“传输语义”。长度、流号、序号这些字段每帧都要读，必须是定长、可直接 unpack 的。")
    BULLET("JSON 体承载“业务语义”。新增字段不影响二进制布局，两端解析器可以只关心自己认识的键。")
    BULLET("二进制载荷单独存放。文件数据不做 Base64、不进 JSON，避免 33% 的膨胀和一次多余的内存拷贝。")
    P("框架选择上，纯 JSON 行协议会把文件数据也塞进文本，纯 protobuf 则要为每个版本重新编译 .proto，"
      "对实验规模都偏重。因此采用“定长头 + JSON + 载荷”的混合封装，本质上与 TCP 报头 + 应用数据的"
      "思路一致，只是把控制字段换成了自描述的 JSON。")

    H2("3.2  报头结构")
    P("每帧以 24 字节报头开始，字段布局如图 2。报头本身带 CRC16，可以在解析 JSON 之前就丢弃被篡改或"
      "错位的帧，避免把畸形数据送进解析器。")
    FIG("fig_header.png", "图 2  SFAP/1 报头字段布局（24 字节，大端序）")
    TABLE(
        ["偏移", "长度", "字段", "说明"],
        [
            ["0", "2", "magic", "固定 0x53 0x46（'SF'）；不匹配直接断链，不进入协议解析"],
            ["2", "1", "version", "协议版本，当前 1；版本不符返回 BAD_FRAME"],
            ["3", "1", "type", "消息类型，高 4 位表示模块，见 3.3"],
            ["4", "1", "flags", "LAST / RESUME / ACKREQ / ERROR"],
            ["5", "1", "reserved", "保留，使报头 4 字节对齐"],
            ["6", "4", "stream_id", "连接内的流标识；0 号流专用于登录与文件系统操作"],
            ["10", "4", "sequence", "流内帧序号，从 0 开始；乱序立即中止该流"],
            ["14", "4", "body_len", "JSON 体长度，上限 16 KiB"],
            ["18", "4", "payload_len", "二进制载荷长度，上限 1 MiB"],
            ["22", "2", "CRC16", "CRC-16/CCITT，覆盖前 22 字节"],
        ],
        widths=[1.4, 1.4, 3.0, 10.4],
        caption="表 4  报头字段定义",
    )
    P("把 body 与 payload 的长度分开，是为了让接收方可以“先读头、再按需读体”：只有数据帧才需要分配"
      "载荷缓冲区，控制帧的 payload_len 恒为 0。")

    H2("3.3  消息类型")
    TABLE(
        ["类型", "名称", "方向", "主要字段"],
        [
            ["0x01 / 0x02", "LOGIN_REQ / LOGIN_RESP", "C→S / S→C",
             "user, pass / role, keepalive, rate_bps, window, chunk, tls"],
            ["0x10 / 0x11", "LIST_REQ / LIST_RESP", "C→S / S→C", "path / entries[name,type,size,mtime]"],
            ["0x12 / 0x13", "STAT_REQ / STAT_RESP", "C→S / S→C", "path / size, sha256"],
            ["0x20 / 0x21", "UPLOAD_REQ / UPLOAD_RESP", "C→S / S→C",
             "path, size, sha256, resume / offset, chunk, window"],
            ["0x22 / 0x23", "DATA / DATA_ACK", "C→S / S→C", "payload 块 / acked 累计字节"],
            ["0x24 / 0x25", "UPLOAD_END / UPLOAD_RESP_END", "C→S / S→C",
             "sha256 / ok, size, sha256, elapsed, rate_mbps"],
            ["0x26", "CANCEL", "双向", "stream（暂停或取消一条流）"],
            ["0x27 / 0x28", "DOWNLOAD_REQ / DOWNLOAD_RESP", "C→S / S→C", "path, offset / size, offset, chunk"],
            ["0x30–0x35", "MKDIR / DELETE / RENAME", "C→S / S→C", "path；src, dst"],
            ["0x40 / 0x41", "PING / PONG", "双向", "ts（毫秒），用于 RTT 与保活"],
            ["0x60", "ERROR", "S→C", "code, message；与请求同流号返回"],
            ["0x70 / 0x71", "BYE / BYE_ACK", "双向", "正常关闭"],
        ],
        widths=[2.6, 5.4, 2.8, 5.4],
        caption="表 5  消息类型表",
    )
    P("所有业务错误都不复用连接级错误：错误帧与请求使用同一个 stream_id 返回，客户端据此把异常抛给"
      "对应的传输对象，其他流不受影响。这一点在并发场景下尤其重要。")

    H2("3.4  标志位与错误码")
    TABLE(
        ["名称", "值", "语义"],
        [
            ["LAST", "0x01", "多帧传输的最后一帧"],
            ["RESUME", "0x02", "本次请求携带断点续传协商（UPLOAD_REQ）或服务端接受了续传（UPLOAD_RESP）"],
            ["ACKREQ", "0x04", "请求立即确认（保留，当前由 ACK 阈值触发）"],
            ["ERROR", "0x08", "业务层失败；与 ERROR 消息配合使用"],
        ],
        widths=[2.6, 2.0, 11.6],
        caption="表 6  标志位定义",
    )
    TABLE(
        ["错误码", "触发场景", "客户端处理"],
        [
            ["AUTH_FAILED", "账号不存在或口令错误", "提示并允许重试，计入锁定计数"],
            ["LOCKED", "同一 IP 或账号 5 次失败后锁定 60 s", "提示剩余时间，禁止继续尝试"],
            ["DENIED", "路径越权、证书与账号不符、流数超限", "终止本次操作，不影响连接"],
            ["NOT_FOUND", "目标文件或流不存在", "刷新视图"],
            ["CONFLICT", "流号被占用、分块乱序、重复登录", "中止该流并记录日志"],
            ["TOO_LARGE", "超出配额（默认 1 GiB）", "提示配额"],
            ["INTEGRITY", "大小或 SHA-256 不匹配", "删除 .part 并提示重传"],
            ["RATE_LIMITED", "控制帧洪泛（>200 帧/秒）", "断链"],
            ["BAD_FRAME", "魔数/版本/CRC/长度非法", "断链"],
        ],
        widths=[3.2, 8.0, 4.6],
        caption="表 7  错误码",
    )

    H2("3.5  连接生命周期")
    TABLE(
        ["状态", "进入条件", "允许的动作", "离开条件"],
        [
            ["TLS_OK", "TCP 建连并完成 TLS 握手（客户端证书通过 CA 校验）", "仅 LOGIN_REQ", "收到登录请求"],
            ["AUTHENTICATING", "收到 LOGIN_REQ", "口令校验、证书 CN 绑定校验", "成功 → READY；失败 → 重试或断链"],
            ["READY", "认证通过，沙箱与限速桶就绪", "LIST / STAT / UPLOAD / DOWNLOAD / PING", "开始传输 → TRANSFERRING"],
            ["TRANSFERRING", "至少有一条活动流", "DATA / ACK / CANCEL / 新开流（≤4）", "全部流结束 → READY"],
            ["CLOSED", "BYE、空闲 75 s、协议违规、洪泛、进程退出", "—", "释放连接配额与文件句柄"],
        ],
        widths=[3.0, 6.0, 4.6, 4.0],
        caption="表 8  会话状态迁移",
    )
    P("状态机严格单向推进：未认证的连接不可能触发文件操作，已认证的连接也不会回到认证态。所有异常路径"
      "都收敛到 CLOSED，并由 finally 释放连接配额——这是服务端不会因为异常而“漏掉”配额的关键。")

    H2("3.6  登录：传输层先认证，应用层再认证")
    P("登录被拆成两个层次。TLS 层用客户端证书证明“你持有 CA 签发的某个私钥”，应用层再用口令证明"
      "“你是这个账号的主人”，最后把证书 CN 与账号名绑定（alice 的账号只接受 CN=alice 的证书），"
      "从而同时抵御“偷到口令但没有证书”和“偷到证书但不知道口令”两种情形。")
    FIG("fig_login_seq.png", "图 3  登录时序")
    P("口令使用 scrypt（N=2^14, r=8, p=1）加 16 字节随机盐存储，校验用 hmac.compare_digest 做常数时间"
      "比较；用户不存在时也执行一次等价开销的哈希，避免通过响应时间枚举账号。")

    H2("3.7  上传与断点续传")
    P("上传的关键是“先协商、再发送”。客户端先算好整个文件的 SHA-256，把大小与摘要一起发给服务端；"
      "服务端检查同名 .part 文件，把已写入的字节数作为 offset 返回。客户端据此 seek 到断点，服务端则"
      "在打开文件时把已有前缀读一遍续算摘要，于是续传后的文件仍然可以用一次 SHA-256 验证完整性。")
    FIG("fig_upload_seq.png", "图 4  上传与断点续传时序")
    P("发送侧维护 4 MiB 的未确认窗口：服务端每 1 MiB 回一个累计 ACK，窗口未滑动时客户端阻塞等待。"
      "这个窗口同时承担三个作用——流量控制、内存上限、以及限速的抓手（服务端只要延迟 ACK，发送方"
      "自然降速）。所有数据写完后，服务端 fsync、比对大小与摘要，再用 os.replace 原子改名，因此"
      "目录里永远不会出现“半个文件被当成完整文件”的状态。")

    H2("3.8  下载与暂停恢复")
    FIG("fig_download_seq.png", "图 5  下载与暂停恢复时序")
    P("下载按 offset 请求，服务端从该位置开始读文件并按角色令牌桶限速发送，最后一帧带 eof 与整文件"
      "SHA-256。客户端先写 .part，校验通过后才改名为目标文件。用户点“暂停”时，客户端发送 CANCEL，"
      "服务端取消发送任务并回报已发送位置；点“继续”时以该位置重新发起 DOWNLOAD_REQ，实现断点续传。")

    H2("3.9  流控、背压与多路复用")
    P("一条 TCP 连接上可以同时存在最多 4 条流（VIP），每条流有独立的 stream_id 与序号，帧交错发送。"
      "接收端按流号投递到对应队列，因此大文件下载不会阻塞小文件上传的 ACK。写侧用一把 asyncio.Lock "
      "串行化“写 + drain”，保证不同任务产生的帧不会在字节层面互相穿插。")
    P("背压来自两个方向：TCP 自身的接收窗口，以及应用层的 4 MiB 确认窗口。前者防止内核缓冲区无限增长，"
      "后者让发送方在服务端处理不过来时主动停下，而不是把数据堆在内存里。")

    H2("3.10  协议正确性论证")
    BULLET("粘包/半包：接收端先 readexactly(24) 取报头，再按 body_len、payload_len 精确读取；EOF 只允许"
           "出现在帧边界，否则视为截断并断链。")
    BULLET("超长帧：解析报头时即校验 body ≤16 KiB、payload ≤1 MiB，超限直接拒绝，避免恶意长度导致内存爆炸。")
    BULLET("乱序与重放：每条流内序号必须连续，否则中止该流；登录只允许一次，重复 LOGIN 返回 CONFLICT。")
    BULLET("头错位：CRC16 覆盖前 22 字节，错位或篡改会在解析 JSON 之前被发现。")
    BULLET("半开连接：读写都有超时（握手 10 s、帧间隔 75 s），心跳每 20 s 一次，连续 3 个周期无响应即断链。")
    BULLET("流号冲突：客户端自增分配流号，服务端校验“该流号未被占用”，避免帧被投递到错误的传输对象。")


# ------------------------------------------------------------------ 4 安全
def part_four() -> None:
    H1("4  安全设计")
    H2("4.1  威胁模型与对策")
    TABLE(
        ["威胁", "攻击方式", "对策", "验证用例"],
        [
            ["中间人", "ARP/DNS 劫持、伪造服务端", "TLS 1.3 + 私有 CA + 客户端校验证书链与主机名", "用例 1"],
            ["身份冒充", "偷口令或偷证书", "口令 scrypt + 证书 CN 与账号绑定，二者缺一不可", "用例 6"],
            ["口令爆破", "字典攻击、撞库", "5 次失败锁定 60 s；用户不存在也做等价哈希", "用例 4、5"],
            ["越权访问", "../../etc/passwd、符号链接逃逸", "路径规范化 + realpath + commonpath；拒绝绝对路径与 ..", "用例 13–17"],
            ["SQL 注入", "' OR '1'='1", "全部参数化查询；不使用字符串拼接 SQL", "用例 5"],
            ["资源耗尽", "海量连接、慢速握手、控制帧洪泛", "单 IP 8 连接、全局 256、握手 10 s、75 s 空闲、200 帧/秒阈值", "用例 19"],
            ["数据篡改", "传输中修改文件内容", "SHA-256 端到端校验 + 帧头 CRC16 + TLS AEAD", "用例 7、8"],
            ["配额滥用", "单账号塞满磁盘", "按角色配额（1/4 GiB），上传前检查", "代码 auth.py"],
        ],
        widths=[2.4, 5.2, 6.6, 3.0],
        caption="表 9  威胁模型与对策",
    )

    H2("4.2  传输层：TLS 双向认证与私有 CA")
    P("实验用 openssl 自建三级信任：根 CA 自签，再用它签发服务端证书（SAN 含 localhost / sfap.local / "
      "127.0.0.1）与每个账号的客户端证书。服务端设置 CERT_REQUIRED，没有客户端证书的连接在握手阶段"
      "就被拒绝，攻击者连协议层都进不来。")
    CODE("""# 生成 CA（scripts/gen_certs.sh 节选）
openssl req -x509 -new -key ca-key.pem -sha256 -days 3650 -out ca-cert.pem \\
  -subj "/CN=SecureFile Lab Root CA" \\
  -addext "basicConstraints=critical,CA:TRUE,pathlen:1" \\
  -addext "keyUsage=critical,keyCertSign,cRLSign"

# 签发客户端证书，CN 必须是账号名
openssl x509 -req -in client-alice.csr -CA ca-cert.pem -CAkey ca-key.pem \\
  -CAcreateserial -out client-alice-cert.pem -days 825 -sha256 -extfile client.ext""")
    P("验证结果：客户端报告 TLSv1.3 / TLS_AES_256_GCM_SHA384 / CN=localhost，说明前进保密性与"
      "证书链校验均已生效（见图 6 右上角）。")

    H2("4.3  身份：scrypt 与证书绑定")
    P("口令库只存盐与派生值，不存明文；认证时的比较是常数时间的。更关键的是第三道校验：登录成功后"
      "比对证书 CN 与账号的 cert_cn 字段，不一致直接 DENIED。测试用例 6 用 bob 的证书登录 alice 账号，"
      "服务端在口令正确的情况下依然拒绝，证明该绑定有效。")

    H2("4.4  授权：服务端目录沙箱与 ACL")
    P("服务端从不把客户端给的字符串直接交给 open()。所有路径先规范化（拒绝绝对路径、盘符、..、"
      "控制字符、Windows 设备名），再拼到用户根目录下并 realpath，最后用 commonpath 确认仍在根目录内。"
      "即使攻击者事先在目录里放了指向 C:\\Windows 的符号链接，realpath 之后也会被 commonpath 拦下。")
    CODE("""def resolve(self, rel, *, must_exist=False):
    clean = normalise(rel)                     # 拒绝 /、C:、..、控制字符、CON 等设备名
    target = (self.root / clean).resolve()     # 解析符号链接
    if os.path.normcase(os.path.commonpath([str(target), str(self.root)])) \\
            != os.path.normcase(str(self.root)):
        raise SandboxError("path escapes home")
    return target""")
    P("进程级权限由脚本固化：Linux 下用独立服务账户 + setfacl 只授 rwX、默认 ACL 让新文件继承权限；"
      "Windows 下用 icacls 关闭继承、只授 filesvc 修改权并移除 Everyone。users.db 放在传输目录之外，"
      "避免用户通过下载接口拿到口令哈希。")
    CODE("""# Linux（scripts/acl_server.sh）
setfacl -R  -m u:filesvc:rwX -m g:filesvc:rX -m o::- /srv/securefile/data
setfacl -R -d -m u:filesvc:rwX -m g:filesvc:rX -m o::- /srv/securefile/data

# Windows（scripts/acl_server.ps1）
icacls D:\\securefile\\data /inheritance:r
icacls D:\\securefile\\data /grant:r "filesvc:(OI)(CI)M" "Administrators:(OI)(CI)F\"""")

    H2("4.5  抗 SQL 注入")
    P("用户库是 SQLite，所有语句使用 ? 占位符。注入载荷 alice' OR '1'='1 会被驱动当作普通字符串，"
      "查不到任何记录；同时它也会被计入失败次数，连续 5 次即锁定来源 IP。测试用例 5 专门覆盖这一点。")

    H2("4.6  可用性：把 DoS 成本抬高")
    TABLE(
        ["机制", "参数", "作用"],
        [
            ["全局连接上限", "256", "防止单机耗尽文件描述符"],
            ["单 IP 连接上限", "8", "限制单点并发，正常用户足够"],
            ["TLS 握手超时", "10 s", "对抗慢速握手（slowloris 变种）"],
            ["空闲超时", "75 s", "回收僵尸连接"],
            ["控制帧速率", "200 帧/秒", "超过即判定洪泛并断链"],
            ["登录失败锁定", "5 次 / 60 s", "抬高口令爆破成本"],
            ["流数上限", "4（VIP）/ 2（普通）", "防止单连接无限开流"],
            ["上传配额", "1 / 4 GiB", "防止塞满磁盘"],
            ["带宽令牌桶", "2 / 8 MiB/s", "保证多用户公平性"],
        ],
        widths=[4.0, 5.0, 8.2],
        caption="表 10  可用性防护参数",
    )
    P("要说明的是，应用层手段无法抵御带宽型 DDoS——那需要上游清洗。本实验能做到的是：在单机资源被"
      "占满之前，让攻击者的每一个连接都付出更高的代价，并保证正常用户仍能完成握手与认证。")

    H2("4.7  完整性：SHA-256、.part 与原子改名")
    P("完整性校验发生在三个层次：TLS 的 AEAD 保证“链路上没被改”，帧头 CRC16 保证“帧没被错位”，"
      "文件级 SHA-256 保证“落地内容与源文件一致”。三者互补：前两者防传输错误，后者防逻辑错误"
      "（例如续传拼错、磁盘写坏）。上传只有在大小与摘要都匹配时才 rename，否则删除 .part 并返回"
      "INTEGRITY。")

    H2("4.8  审计")
    P("登录、开流、完成、删除、洪泛等事件写入 SQLite 的 audit 表，包含时间、账号、来源 IP、动作、"
      "细节与结果。审计与业务库同库不同表，便于事后追溯“谁在什么时候动了哪个文件”。")


# ------------------------------------------------------------------ 5 实现
def part_five() -> None:
    H1("5  关键实现")
    H2("5.1  服务端的并发模型")
    P("asyncio.start_server 为每条连接派生一个协程，会话内部再为每个下载创建任务。所有出站帧都经过"
      "同一个 FrameWriter，它用一把锁包住 write + drain，因此多个任务并发发送时帧不会交错。上传不另"
      "开任务，直接在读循环里处理，避免为每个 256 KiB 分块创建协程。")
    P("取消是这套模型里最容易出错的地方：下载任务被取消时，必须在 except CancelledError 里补发一帧"
      "带 cancelled 与 offset 的结束帧，客户端才知道“停在哪”；同时 do_cancel 只负责 cancel，不负责"
      "计数，计数统一在任务的 done_callback 里减一，避免重复扣减。")

    H2("5.2  客户端的线程模型")
    P("Tk 不是线程安全的，因此客户端把网络全部放进 AsyncWorker（独立线程 + 独立事件循环），GUI 线程"
      "只做两件事：提交协程、消费事件队列。进度回调不直接碰控件，而是把 (tid, done, total) 塞进"
      "queue.Queue，由 200 ms 的 after 定时器统一刷新表格。这样即使传输很密集，界面也不会因为跨线程"
      "调用而崩溃。")

    H2("5.3  令牌桶与限速")
    P("令牌桶按角色初始化（admin 不限速、VIP 8 MiB/s、普通 2 MiB/s），桶容量取 1 MiB，避免“一秒突发”"
      "让小文件跑出远超标称值的速度。下载时限速发生在发送每一块之前；上传时限速发生在服务端写盘之前，"
      "通过延迟 ACK 把压力传导回发送方的窗口。实测 VIP 与普通用户的上传/下载速率比分别为 3.94 与 4.07，"
      "与配置的 4 倍基本一致（表 12）。")

    H2("5.4  心跳与超时")
    P("登录响应里下发 keepalive=20 s。两端各自维护 last_send / last_recv：空闲 20 s 发 PING，收到 PONG "
      "计算 RTT 并显示在状态栏；连续 3 个周期没有任何入站帧则主动断链。读循环本身还有 75 s 的 wait_for，"
      "防止对端“连上了但永不发帧”。")

    H2("5.5  断点续传的两个细节")
    BULLET("续传摘要：服务端打开 .part 后先把已有前缀读一遍喂给 hasher，保证续传完成后仍是一次完整的"
           "SHA-256，而不是“后半段的摘要”。")
    BULLET("续传与并发：暂停会取消该流并保留 .part，但服务端不保留会话内的流状态；继续时以新流号重新"
           "协商 offset。这样即使客户端换了进程、换了机器，只要 .part 在，就能接着传。")


# ------------------------------------------------------------------ 6 测试
def part_six() -> None:
    H1("6  测试与结果")
    H2("6.1  测试环境")
    P("服务端与客户端运行在同一台 Windows 11 机器上（127.0.0.1），Python 3.13.0，TLS 1.3，"
      "测试脚本通过真实 TLS 连接驱动，不 mock 任何网络层。执行 python tests/e2e.py 即可复现。")

    H2("6.2  功能与安全用例")
    P("共 19 项断言，全部通过，总耗时约 10 s。用例覆盖正常路径、边界条件与攻击路径。")
    TABLE(
        ["#", "用例", "预期", "结果"],
        [
            ["1", "TLS 1.3 双向认证握手", "报告 TLSv1.3 与套件名", "通过"],
            ["2", "口令 + 证书绑定登录", "返回 role=vip、keepalive=20 s", "通过"],
            ["3", "目录列举", "返回 entries 数组", "通过"],
            ["4", "错误口令被拒绝", "AUTH_FAILED", "通过"],
            ["5", "SQL 注入登录被拒绝", "AUTH_FAILED", "通过"],
            ["6", "证书与账号不匹配", "DENIED（bob 证书 + alice 账号）", "通过"],
            ["7", "上传 3 MiB 并校验 SHA-256", "摘要一致，约 68 MiB/s", "通过"],
            ["8", "下载并还原 SHA-256", "摘要一致", "通过"],
            ["9", "暂停时保留 .part 断点", "断点文件非空", "通过"],
            ["10", "断点续传后内容一致", "从 2.36 MB 处续传，摘要一致", "通过"],
            ["11", "下载断点续传", "从 4.45 MB 处续传完成", "通过"],
            ["12", "单连接多流并发上传", "3 条流同时完成", "通过"],
            ["13", "越权路径 ../escape.bin", "DENIED", "通过"],
            ["14", "越权路径 ..\\\\escape.bin", "DENIED", "通过"],
            ["15", "绝对路径 /etc/passwd", "DENIED", "通过"],
            ["16", "Windows 盘符路径 C:\\\\Windows\\\\win.ini", "DENIED", "通过"],
            ["17", "越权下载 ../../etc/passwd", "DENIED", "通过"],
            ["18", "长连接心跳保活", "RTT 1 ms，连接未断", "通过"],
            ["19", "单 IP 连接数上限", "8 接受 / 2 拒绝", "通过"],
        ],
        widths=[0.9, 6.6, 6.6, 1.8],
        caption="表 11  端到端与安全用例",
    )

    H2("6.3  性能与限速")
    P("传输 24 MiB 文件，每角色 3 轮取均值。下载由服务端令牌桶直接限速，上传通过延迟 ACK 间接限速，"
      "两者都收敛到配置值。")
    TABLE(
        ["账号", "角色", "配置限速", "实测上传", "实测下载", "倍率（相对普通用户）"],
        [
            ["alice", "vip", "8 MiB/s", "8.2 MiB/s", "8.2 MiB/s", "3.94× / 4.07×"],
            ["bob", "normal", "2 MiB/s", "2.1 MiB/s", "2.0 MiB/s", "1.00×"],
        ],
        widths=[2.2, 2.2, 3.2, 3.2, 3.2, 4.4],
        caption="表 12  按角色限速的实测结果",
    )
    P("本机回环下的裸传输速率约 68 MiB/s（用例 7），说明限速是配置生效的结果，而不是协议本身的瓶颈。")

    H2("6.4  界面")
    P("客户端为单窗口三栏布局：上半部分是本地/远程文件双栏，中部是传输队列（进度、速率、状态），"
      "底部是运行日志与状态栏（角色、配额、限速、RTT）。")
    FIG("gui_connected.png", "图 6  登录成功：远程目录、TLS 摘要与状态栏")
    FIG("gui_transfer.png", "图 7  传输进行中：进度、速率与日志")
    FIG("gui_paused.png", "图 8  暂停后保留断点，可随时继续")

    H2("6.5  调试过程中修复的三个缺陷")
    P("这三处都不是“功能没写”，而是“边界没考虑”，记录下来作为方法论的一部分：")
    BULLET("报头字段数不匹配：struct 定义 10 个字段，打包时只给了 9 个（CRC 单独拼），导致首帧即抛"
           "struct.error。教训是二进制格式应当有单元测试，而不是只在联调时暴露。")
    BULLET("错误帧走错流：服务端拒绝路径穿越时用默认 stream=0 回错误，而请求在 stream=N 上，客户端"
           "等不到响应直到超时。修复方式是所有错误帧必须回显请求的流号——这正是多路复用协议必须"
           "遵守的对称性。")
    BULLET("关闭连接阻塞 20 s：Windows 上 TLS 传输的 wait_closed 可能迟迟不返回 connection_lost，"
           "导致连接配额迟迟不释放。改为 close() 后不再等待，配额随之立即归还。")


# ------------------------------------------------------------------ 7 加分
def part_seven() -> None:
    H1("7  加分项")
    TABLE(
        ["加分项", "实现情况", "说明"],
        [
            ["文件断点续传", "已实现", "上传按 .part 长度协商 offset；下载按本地 .part 大小续传；"
                                        "两侧都以 SHA-256 收尾（用例 9–11）"],
            ["基于公钥的身份验证", "已实现", "私有 CA + 客户端证书双向认证，证书 CN 与账号绑定（4.2、4.3）"],
            ["同时上传/下载多个文件", "已实现", "单连接 4 条流复用，GUI 支持多选并发（用例 12）"],
            ["GUI 支持", "已实现", "双栏浏览、传输队列、进度/速率、暂停/继续/取消、日志、状态栏"],
            ["按用户身份控制带宽", "已实现", "admin 不限速、VIP 8 MiB/s、普通 2 MiB/s，实测倍率 3.94×（表 12）"],
        ],
        widths=[4.2, 2.6, 10.4],
        caption="表 13  加分项完成情况",
    )
    P("五项加分项全部落地。其中“断点续传”与“证书认证”不是演示级的开关，而是参与协议状态机与"
      "摘要链路的正式路径：续传要能通过最终的 SHA-256，证书不匹配则在认证阶段就被拒绝。")


# ------------------------------------------------------------------ 8 部署
def part_eight() -> None:
    H1("8  部署与复现")
    P("以下命令在工程根目录（securefile/）执行。Windows 建议使用 Git Bash，PowerShell 亦可。")
    CODE("""# 1) 生成 PKI（CA / 服务端 / 三个演示账号的客户端证书）
bash scripts/gen_certs.sh run/certs

# 2) 初始化用户库（alice/vip、bob/normal、admin/admin）
python auth.py --db run/state/users.db --init

# 3) 启动服务端
python server.py --config config.server.json

# 4) 启动图形客户端（另开一个终端）
python client_gui.py

# 5) 自动化验证（服务端运行中）
python tests/e2e.py --port 9443
python tests/benchmark.py --port 9443

# 6) 初始化 Git 仓库（可选，会生成 6 条逻辑提交）
bash scripts/init_repo.sh

# 7) 打包提交物：只生成 ZIP、不加密
bash scripts/package.sh 张三 202618008829001 ../demo.mp4""")
    P("演示账号与口令：alice / Alice@2026（证书 CN=alice）、bob / Bob@2026、admin / Admin@2026。"
      "客户端登录时必须选择对应账号的证书，否则会被证书绑定校验拒绝——这不是缺陷，而是设计。")
    P("服务端目录 ACL 需管理员权限执行一次：Linux 用 scripts/acl_server.sh，Windows 用 "
      "scripts/acl_server.ps1。脚本会创建数据目录、收紧权限、并把数据库移出传输沙箱。")

    H2("8.1  演示视频拍摄清单")
    P("课件要求视频展示“编译、部署、测试”全过程。Python 无编译产物，可用 py_compile 与单元测试替代"
      "“构建”环节，其余按下列顺序录制，约 5 分钟：")
    CODE("""0:00  说明实验目标与技术选型（30 s）
0:30  bash scripts/gen_certs.sh 生成证书；openssl x509 查看 SAN
1:00  python auth.py --init；sqlite3 展示 users 表只有盐与派生值
1:20  启动 server.py；展示监听日志与 data/ 目录 ACL
1:50  启动 GUI：连接、登录（指出 TLS 1.3 与 CN）
2:20  双栏浏览、新建目录、上传（展示进度与速率）
3:00  暂停 → 展示 .part 与断点 → 继续 → 完成（对比 SHA-256）
3:50  下载同样演示一次暂停/继续
4:20  终端运行 tests/e2e.py，19 项全绿
4:50  演示攻击：错误口令、SQL 注入、../ 越权、9 条连接被拒
5:20  VIP 与普通账号限速对比（benchmark.py 输出）""")


# ---------------------------------------------------------------- 9 总结
def part_nine() -> None:
    H1("9  不足与改进")
    P("把不足写清楚，比把优点写满更有价值。以下四点是目前确实存在的限制：")
    BULLET("配额统计是 O(n)：每次上传前遍历用户目录求和，文件多时会有明显延迟。改进方向是维护增量"
           "计数（上传 +size、删除 -size），或直接落库。")
    BULLET("续传只校验长度：服务端接受 .part 时只信长度，不校验前缀内容。若 .part 被替换成同样长度的"
           "垃圾，最终 SHA-256 会拒绝并删除，但浪费了一次传输。可在 .part 旁存一份前缀摘要解决。")
    BULLET("未做真正的 DDoS 防护：应用层只能抬高成本，带宽型攻击仍需上游清洗或 eBPF/XDP 层过滤。"
           "这一层在实验环境里无法验证。")
    BULLET("GUI 观感与可访问性一般：Tk 的控件体系有限，进度条用字符绘制，高 DPI 下需要系统缩放。"
           "若重做，会考虑 Web 前端 + 本地 agent 的架构。")
    P("如果继续做下去，优先级最高的是把“前缀摘要”补上，其次是给协议加一个可选的压缩标志位"
      "（文本类文件收益明显），最后是把服务端拆成可水平扩展的多进程模型。")


def appendix() -> None:
    H1("附录 A  协议速查")
    CODE("""帧 = 24B 报头 + JSON 体 + 二进制载荷
报头 = magic(2) | ver(1) | type(1) | flags(1) | rsvd(1)
     | stream_id(4) | seq(4) | body_len(4) | payload_len(4) | crc16(2)

一次上传 = UPLOAD_REQ → UPLOAD_RESP(offset) → DATA* → DATA_ACK*
          → UPLOAD_END → UPLOAD_RESP_END

一次下载 = DOWNLOAD_REQ(offset) → DOWNLOAD_RESP → DATA* → DATA(eof, sha256)

结束连接 = BYE → BYE_ACK → close""")

    H1("附录 B  AI 工具使用说明")
    P("课件建议“核心模块自己动手，GUI 与 CRUD 可交给 Agent”。本实验的实际分工是：协议设计、安全"
      "边界、并发与取消逻辑由本人完成并逐行复查；目录树渲染、表格填充、样式调整等重复性代码借助"
      "AI 生成后手工修改；报告中的图由脚本绘制，数据全部来自真实运行输出，未使用任何虚构的测试结果。")
    P("需要说明的是，AI 生成的代码同样经过测试用例验证——19 项用例就是验收标准；凡是跑不通的实现，"
      "无论出自谁手都退回重写。")


# ------------------------------------------------------------------- build
def main() -> None:
    cover()
    part_one()
    part_two()
    part_three()
    part_four()
    part_five()
    part_six()
    part_seven()
    part_eight()
    part_nine()
    appendix()

    # page numbers in footer
    footer = doc.sections[0].footer
    para = footer.paragraphs[0]
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_end)
    cn(run, size=9, color=GREY)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print("wrote", OUT, OUT.stat().st_size // 1024, "KiB")


if __name__ == "__main__":
    main()
