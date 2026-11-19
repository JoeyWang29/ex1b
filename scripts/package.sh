#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 打包提交物：姓名_学号_EX1B.zip
#
#   ./package.sh "张三" "202618008829001" [演示视频路径]
#
# 产物结构（严格按课件要求，只提交 ZIP，不加密）：
#   姓名_学号_EX1B/
#     姓名_学号_ex1B_src/           源码（不含 run/ 与缓存）
#     姓名_学号_ex1B_report.pdf     报告
#     姓名_学号_ex1B_play.mp4       演示视频（若提供）
# ---------------------------------------------------------------------------
set -euo pipefail

NAME="${1:-}"
SID="${2:-}"
VIDEO="${3:-}"

if [[ -z "$NAME" || -z "$SID" ]]; then
  echo "usage: $0 <姓名> <学号> [演示视频]" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/../deliverable"
STAGE="$OUT/${NAME}_${SID}_EX1B"
SRC="$STAGE/${NAME}_${SID}_ex1B_src"

rm -rf "$STAGE"
mkdir -p "$SRC"

echo "[1/4] copy source"
( cd "$ROOT" && tar -cf - \
    --exclude='run' --exclude='__pycache__' --exclude='.git' \
    --exclude='*.pyc' --exclude='docs/report.docx' --exclude='docs/report.pdf' \
    --exclude='docs/figures/fig_state.png' . ) | ( cd "$SRC" && tar -xf - )

echo "[2/4] copy report"
if [[ -f "$ROOT/docs/report.pdf" ]]; then
  cp "$ROOT/docs/report.pdf" "$STAGE/${NAME}_${SID}_ex1B_report.pdf"
else
  echo "  ! docs/report.pdf 不存在，先运行 python docs/make_report.py 并导出 PDF" >&2
fi

echo "[3/4] copy video"
if [[ -n "$VIDEO" && -f "$VIDEO" ]]; then
  cp "$VIDEO" "$STAGE/${NAME}_${SID}_ex1B_play.mp4"
else
  echo "  ! 未提供演示视频，提交前请补 ${NAME}_${SID}_ex1B_play.mp4（见 docs/demo_script.md）"
fi

echo "[4/4] zip"
python - "$STAGE" "$OUT/${NAME}_${SID}_EX1B.zip" <<'PY'
import os, sys, zipfile
stage, target = sys.argv[1], sys.argv[2]
root = os.path.dirname(stage)
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for base, dirs, files in os.walk(stage):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            full = os.path.join(base, name)
            zf.write(full, os.path.relpath(full, root))
print("zip ok:", target, os.path.getsize(target) // 1024, "KiB")
PY

echo
echo "done -> $OUT/${NAME}_${SID}_EX1B.zip"
du -sh "$STAGE" 2>/dev/null || true
