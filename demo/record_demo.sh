#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 录制并合成演示视频（两段：部署/测试 + 图形客户端）
#
#   ./record_demo.sh
#
# 依赖：ffmpeg（默认用 ex1b/.tools 下的静态版本）、Python 3.13（带 tkinter）
# 产物：demo/out/姓名_学号_ex1B_play.mp4
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FF="${FFMPEG:-$ROOT/../.tools/ffmpeg-win-x86_64-v9.0.2.exe}"
PY="${PYTHON:-C:/Users/29166/AppData/Local/Programs/Python/Python313/python.exe}"
OUT="$ROOT/demo/out"
mkdir -p "$OUT"
cd "$ROOT"

STYLE="FontName=Microsoft YaHei,FontSize=11,PrimaryColour=&H00FFFFFF,OutlineColour=&H60000000,BorderStyle=1,Outline=1,Shadow=0,MarginV=22"
VF1="crop=1600:980:0:0,pad=1600:1080:0:0:color=black,subtitles=%s:force_style='%s'"
VF2="scale=-2:980:flags=lanczos,pad=1600:1080:(ow-iw)/2:0:color=black,subtitles=%s:force_style='%s'"

echo "[pre] 检查桌面状态"
"$PY" - <<'PYEOF'
import ctypes, sys
u = ctypes.windll.user32
fg = u.GetForegroundWindow()
print("  foreground window:", fg)
if fg == 0:
    print("  ! 桌面已锁屏：录屏只会得到黑屏，请先解锁再重试")
    sys.exit(2)
PYEOF

echo "[0/4] 准备 PKI 与用户库（与服务端共用同一套证书）"
# keep the display awake for the whole take (does not bypass the lock policy)
"$PY" -c "import ctypes,time; ctypes.windll.kernel32.SetThreadExecutionState(0x80000000|0x00000002); time.sleep(240)" &
bash scripts/gen_certs.sh run/certs >/dev/null 2>&1
"$PY" auth.py --db run/state/users.db --init >/dev/null
echo "  pki ready"

echo "[0/4] 启动服务端"
"$PY" server.py --config config.server.json --host 127.0.0.1 --port 9443 --log run/server.log > run/server.console 2>&1 &
SRV_PID=$!
sleep 3
netstat -ano | grep -q ":9443" && echo "  server up (pid $SRV_PID)"

echo "[1/4] 录制部署与测试（约 75 s）"
rm -f "$OUT/console_hwnd.txt"
"$PY" tools/launch_console.py demo/deploy_demo.bat
for _ in $(seq 1 20); do
  [[ -f "$OUT/console_hwnd.txt" ]] && break
  sleep 0.25
done
CHWND="$(cat "$OUT/console_hwnd.txt" 2>/dev/null || echo 0)"
CX=0; CY=0; CW=1600; CH=980
if [[ -f "$OUT/console_rect.txt" ]]; then
  RX=0; RY=0; RW=1600; RH=980
  read -r RX RY RW RH < "$OUT/console_rect.txt" || true
  CX=$RX; CY=$RY; CW=1600; CH=980
  if [[ "$RW" -lt 1600 ]]; then CW=$RW; fi
  if [[ "$RH" -lt 980 ]]; then CH=$RH; fi
fi
echo "  console hwnd=$CHWND rect=${CX},${CY} crop=${CW}x${CH}"
VF1="crop=${CW}:${CH}:${CX}:${CY},pad=1600:1080:0:0:color=black,subtitles=%s:force_style='%s'"
"$FF" -hide_banner -loglevel error -y -f gdigrab -framerate 15 -t 74 -i desktop \
  -vf "$(printf "$VF1" "demo/deploy.srt" "$STYLE")" \
  -c:v libx264 -preset veryfast -crf 24 -pix_fmt yuv420p -movflags +faststart "$OUT/seg1.mp4"
sleep 1

echo "[2/4] 录制图形客户端（约 58 s）"
rm -f "$OUT/hwnd.txt"
"$PY" tools/demo_director.py &
DIR_PID=$!
for _ in $(seq 1 40); do
  [[ -f "$OUT/hwnd.txt" ]] && break
  sleep 0.25
done
if [[ ! -f "$OUT/hwnd.txt" ]]; then
  echo "  ! 客户端窗口没有启动，检查 tkinter 或证书路径" >&2
  kill $DIR_PID 2>/dev/null || true
  exit 1
fi
HWND="$(cat "$OUT/hwnd.txt")"
echo "  window hwnd=$HWND"
sleep 1
"$FF" -hide_banner -loglevel error -y -f gdigrab -framerate 15 -t 58 -i "hwnd=$HWND" \
  -vf "$(printf "$VF2" "demo/gui.srt" "$STYLE")" \
  -c:v libx264 -preset veryfast -crf 24 -pix_fmt yuv420p -movflags +faststart "$OUT/seg2.mp4"
wait $DIR_PID 2>/dev/null || true

echo "[3/4] 拼接"
printf "file '%s'\nfile '%s'\n" "$(cygpath -w "$OUT/seg1.mp4")" "$(cygpath -w "$OUT/seg2.mp4")" > "$OUT/list.txt"
"$FF" -hide_banner -loglevel error -y -f concat -safe 0 -i "$OUT/list.txt" -c copy "$OUT/play_silent.mp4"

echo "[4/4] 收尾"
TARGET="$OUT/王恩泽_202628007329016_ex1B_play.mp4"
mv "$OUT/play_silent.mp4" "$TARGET"
rm -f "$OUT/seg1.mp4" "$OUT/seg2.mp4" "$OUT/list.txt"
kill $SRV_PID 2>/dev/null || true
ls -lh "$TARGET"
echo "done -> $TARGET"
