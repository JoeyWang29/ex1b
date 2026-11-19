#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 初始化 Git 仓库并生成一条可读的提交历史。
#
# 用法：
#   git config --global user.name  "你的名字"
#   git config --global user.email "你的邮箱"
#   ./scripts/init_repo.sh [远程仓库地址]
#
# 仓库要求（课件）：GitHub / Gitee / GitLab 均可，必须有完整提交记录，
# 提交后再把仓库设为 public 也可以。
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${1:-}"
cd "$ROOT"

if [[ -n "$(git status --porcelain 2>/dev/null || true)" ]] && [[ -d .git ]]; then
  echo "! 当前目录已经是 git 仓库且有未提交改动，脚本不做任何事。" >&2
  exit 1
fi

git init -b main

commit() {
  local message="$1"; shift
  git add -- "$@"
  git commit -q -m "$message"
  echo "  + $message"
}

echo "[1/6] 工程骨架"
commit "chore: project skeleton, config and build scripts" \
  .gitignore config.server.json

echo "[2/6] 协议层"
commit "feat(protocol): SFAP/1 frame codec with 24-byte header and CRC16" \
  protocol.py

echo "[3/6] 服务端"
commit "feat(server): asyncio TLS server with session state machine and stream multiplexing" \
  server.py

echo "[4/6] 客户端"
commit "feat(client): TLS transport, resumable transfers and Tk GUI" \
  client_core.py client_gui.py

echo "[5/6] 安全与脚本"
commit "feat(security): scrypt auth, path sandbox, rate limiting, PKI and ACL scripts" \
  auth.py sandbox.py ratelimit.py scripts/

echo "[6/6] 测试与文档"
commit "test/docs: 19-case e2e suite, benchmark, report sources" \
  tests/ docs/ tools/

if [[ -n "$REMOTE" ]]; then
  git remote add origin "$REMOTE"
  git push -u origin main
  echo "pushed to $REMOTE"
fi

git log --oneline
echo
echo "完成。把仓库地址填进报告封面与 1.2 节即可。"
