# 演示视频拍摄清单（约 5 分钟）

课件要求视频展示“程序编译、部署、测试的全过程”。Python 没有编译产物，用
`python -m py_compile` 与单元测试代替“构建”环节，其余按下面的顺序录制即可。
建议 1920×1080、屏幕录制 + 麦克风讲解，窗口最大化。

| 时间 | 画面 | 讲解要点 |
|------|------|----------|
| 0:00 | 报告封面 / 目录树 | 一句话说明：实现了自定义应用层协议 SFAP/1 的安全文件传输系统，二选一里选的是 1B |
| 0:30 | 终端执行 `bash scripts/gen_certs.sh`，随后 `openssl x509 -in run/certs/server-cert.pem -noout -ext subjectAltName` | 私有 CA、服务端 SAN、每个账号一张客户端证书；强调“没有客户端证书连握手都过不去” |
| 1:00 | `python auth.py --db run/state/users.db --init`，用 sqlite3 打开 users 表 | 数据库里只有盐和 scrypt 派生值，没有明文口令 |
| 1:20 | `python -m py_compile *.py` 与 `python tests/e2e.py` 的开头 | 说明“构建”步骤对本项目就是语法编译检查 + 自动化用例 |
| 1:40 | 启动 `python server.py --config config.server.json` | 展示监听日志、TLS 双向认证、数据目录 |
| 1:55 | 启动 `python client_gui.py`，连接并登录 | 指出右上角 TLSv1.3 / TLS_AES_256_GCM_SHA384 / CN=localhost，说明双向认证 |
| 2:20 | 远程目录浏览、新建目录 | 演示路径沙箱：试图输入 `../` 会被拒绝 |
| 2:40 | 上传一个大文件，展示进度/速率 | 指出 4 MiB 窗口与 8 MiB/s 限速（VIP） |
| 3:10 | 点“暂停”，展示 .part 与断点；点“继续”直到完成 | 关键：续传后仍能通过 SHA-256，说明前缀摘要被续算 |
| 3:50 | 下载同一文件，同样暂停/继续 | 服务端限速发送，客户端 .part 落盘 |
| 4:20 | 终端跑 `tests/e2e.py`，19 项全绿 | 逐条念出关键用例：错误口令、SQL 注入、证书不匹配、越权路径、连接上限 |
| 4:50 | `tests/benchmark.py` | VIP 8 MiB/s 与普通 2 MiB/s 的实测倍率 ≈ 4× |
| 5:10 | 用 bob 的证书登录 alice 账号 | 现场演示证书绑定拒绝（DENIED），收尾 |

## 录制前的准备

1. 服务端先起好，确认 `run/certs` 与 `run/state/users.db` 存在。
2. 桌面清空，关掉无关窗口（避免泄露个人信息）。
3. 终端字号调到 16–18 pt，命令提前写进一个 `demo.sh` 里逐条粘贴，避免手误。
4. 如果使用 OBS，建议 30 fps、码率 6 Mbps；录完检查音画同步。

## 文件命名

`姓名_学号_ex1B_play.mp4`，与源码、报告一起放进 `姓名_学号_EX1B/`。
