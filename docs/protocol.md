# SFAP/1 —— SecureFile 应用层协议规范

版本 1.0 · 2026-11

## 1. 传输与分层

SFAP/1 运行在 TCP 之上，外层由 TLS 1.2/1.3 保护，服务端强制要求客户端证书。
一条 TCP 连接称为一个会话（session），会话内可并行多条流（stream），流由 32 位
`stream_id` 标识，0 号流保留给登录与文件系统操作。

```
+---------------------------------------------------+
| 应用语义：登录 / 列目录 / 上传 / 下载 / 心跳        |
+---------------------------------------------------+
| SFAP/1：24B 报头 + JSON 体 + 二进制载荷            |
+---------------------------------------------------+
| TLS 1.2 / 1.3（双向证书认证、AEAD）                |
+---------------------------------------------------+
| TCP                                                |
+---------------------------------------------------+
```

## 2. 帧格式

固定 24 字节报头，大端序：

| 偏移 | 长度 | 字段 | 说明 |
|-----:|-----:|------|------|
| 0 | 2 | magic | `0x53 0x46`（"SF"） |
| 2 | 1 | version | 当前 1 |
| 3 | 1 | type | 消息类型 |
| 4 | 1 | flags | 位标志 |
| 5 | 1 | reserved | 保留，4 字节对齐 |
| 6 | 4 | stream_id | 流标识，0 为控制流 |
| 10 | 4 | sequence | 流内序号，从 0 递增 |
| 14 | 4 | body_len | JSON 体长度，≤ 16 KiB |
| 18 | 4 | payload_len | 载荷长度，≤ 1 MiB |
| 22 | 2 | CRC16 | CRC-16/CCITT，覆盖 0..21 |

约束：

* 收到的帧若 magic / version / CRC 不符，立即断链；
* `body` 必须是 UTF-8 JSON 对象；
* 同一流内 `sequence` 必须严格连续，乱序即中止该流。

## 3. 标志位

| 名称 | 值 | 含义 |
|------|----|------|
| LAST | 0x01 | 多帧传输的最后一帧 |
| RESUME | 0x02 | 断点续传协商 |
| ACKREQ | 0x04 | 请求立即确认（保留） |
| ERROR | 0x08 | 业务失败 |

## 4. 消息

| 类型 | 名称 | 方向 | 字段 |
|------|------|------|------|
| 0x01 | LOGIN_REQ | C→S | user, pass, client, proto |
| 0x02 | LOGIN_RESP | S→C | ok, user, role, keepalive, idle_timeout, rate_bps, max_streams, quota_mb, chunk, window, tls, cipher |
| 0x10 | LIST_REQ | C→S | path |
| 0x11 | LIST_RESP | S→C | path, entries[{name,type,size,mtime}] |
| 0x12 | STAT_REQ | C→S | path |
| 0x13 | STAT_RESP | S→C | path, size, sha256 |
| 0x20 | UPLOAD_REQ | C→S | path, size, sha256, resume |
| 0x21 | UPLOAD_RESP | S→C | stream, offset, chunk, window |
| 0x22 | DATA | 双向 | payload |
| 0x23 | DATA_ACK | S→C | stream, acked |
| 0x24 | UPLOAD_END | C→S | sha256 |
| 0x25 | UPLOAD_RESP_END | S→C | ok, path, size, sha256, elapsed, rate_mbps 或 code/message |
| 0x26 | CANCEL | 双向 | stream |
| 0x27 | DOWNLOAD_REQ | C→S | path, offset |
| 0x28 | DOWNLOAD_RESP | S→C | stream, path, size, offset, chunk |
| 0x30 | MKDIR_REQ | C→S | path |
| 0x31 | MKDIR_RESP | S→C | ok |
| 0x32 | DELETE_REQ | C→S | path |
| 0x33 | DELETE_RESP | S→C | ok |
| 0x34 | RENAME_REQ | C→S | src, dst |
| 0x35 | RENAME_RESP | S→C | ok |
| 0x40 | PING | 双向 | ts |
| 0x41 | PONG | 双向 | ts |
| 0x60 | ERROR | S→C | code, message |
| 0x70 | BYE | 双向 | — |
| 0x71 | BYE_ACK | 双向 | — |

## 5. 典型流程

### 5.1 登录

```
C: LOGIN_REQ{user, pass}          （TLS 已完成双向认证）
S: 校验口令（scrypt，常数时间比较）+ 证书 CN 与账号绑定
S: LOGIN_RESP{role, keepalive=20, window=4MiB, chunk=256KiB}
双方：每 20 s PING/PONG，75 s 无入站帧则断链
```

失败返回 `AUTH_FAILED` / `DENIED` / `LOCKED`，同一 IP 或账号 5 次失败锁定 60 s。

### 5.2 上传（含断点续传）

```
C: UPLOAD_REQ{path, size, sha256, resume=true}
S: 读取 <path>.part 长度 → offset
S: UPLOAD_RESP{offset}
C: seek(offset)；发送 DATA[seq=0..]
S: 每 1 MiB 回 DATA_ACK{acked}
C: UPLOAD_END{sha256}
S: 校验大小与 SHA-256 → fsync → 原子 rename → UPLOAD_RESP_END{ok}
```

窗口 4 MiB：`sent - acked > 4 MiB` 时客户端阻塞，形成端到端背压。

### 5.3 下载（含暂停恢复）

```
C: DOWNLOAD_REQ{path, offset}
S: DOWNLOAD_RESP{size} 然后 DATA[...]，受角色令牌桶限速
S: DATA{eof, sha256}
C: 写 .part → 校验 → rename
暂停：C → CANCEL{stream}；S 取消任务并回报已发送 offset
继续：C → DOWNLOAD_REQ{offset}
```

## 6. 错误码

| 码 | 含义 |
|----|------|
| AUTH_FAILED | 凭据错误 |
| LOCKED | 失败次数过多，锁定中 |
| DENIED | 越权 / 证书不符 / 流超限 |
| NOT_FOUND | 文件或流不存在 |
| CONFLICT | 流号冲突、乱序、重复登录 |
| TOO_LARGE | 超配额或超帧长 |
| INTEGRITY | 大小或摘要不匹配 |
| RATE_LIMITED | 控制帧洪泛 |
| BAD_FRAME | 报头非法 |
| TIMEOUT / CLOSED | 客户端侧：响应超时 / 连接已关闭 |

## 7. 一致性要求

1. 错误帧必须使用请求的 `stream_id` 返回。
2. 流号在同一条连接内不得复用（除取消后重新协商）。
3. 服务端必须在 `UPLOAD_END` 后才发布文件，任何异常都不得暴露半成品。
4. 心跳与业务帧共享同一条连接，任何一方连续 3 个心跳周期无入站帧即视为失效。
