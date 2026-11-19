#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 服务端目录 ACL —— 最小权限原则
#
# 目标：即使 SecureFile 服务进程被攻陷，攻击者也只能读写 $DATA_ROOT 内部，
#      无法触达 /etc、其他用户家目录或数据库文件。
#
# 做法：
#   1) 用独立系统账户 filesvc 运行服务（不要用 root / 登录账户）；
#   2) DATA_ROOT 属主 root:filesvc，权限 0750，others 无任何权限；
#   3) 每个用户一个子目录，只授予 filesvc rwX，其余账户 rx；
#   4) 默认 ACL 让新建文件继承同样的权限，避免“后来新建的文件权限漂移”；
#   5) 数据库 users.db 单独放到 DATA_ROOT 之外，权限 0640，仅 root+filesvc。
#
# 用法：sudo ./acl_server.sh [DATA_ROOT] [SVC_USER]
# ---------------------------------------------------------------------------
set -euo pipefail

DATA_ROOT="${1:-/srv/securefile/data}"
DB_DIR="${2:-/srv/securefile/state}"
SVC_USER="${3:-filesvc}"
SVC_GROUP="${4:-filesvc}"

if [[ $EUID -ne 0 ]]; then
  echo "must run as root (needs chown/setfacl)" >&2
  exit 1
fi

echo "[1/5] service account"
id -u "$SVC_USER" >/dev/null 2>&1 || useradd --system --shell /usr/sbin/nologin "$SVC_USER"

echo "[2/5] data root $DATA_ROOT"
install -d -m 0750 -o root -g "$SVC_GROUP" "$DATA_ROOT"
for U in alice bob admin; do
  install -d -m 0750 -o "$SVC_USER" -g "$SVC_GROUP" "$DATA_ROOT/$U"
done

echo "[3/5] ACL: $SVC_USER -> rwX inside $DATA_ROOT only"
setfacl -R  -m "u:${SVC_USER}:rwX" -m "g:${SVC_GROUP}:rX" -m "o::-" "$DATA_ROOT"
setfacl -R -d -m "u:${SVC_USER}:rwX" -m "g:${SVC_GROUP}:rX" -m "o::-" "$DATA_ROOT"
chmod 0750 "$DATA_ROOT"

echo "[4/5] state dir $DB_DIR (users.db lives outside the transfer sandbox)"
install -d -m 0750 -o root -g "$SVC_GROUP" "$DB_DIR"
chown "root:${SVC_GROUP}" "$DB_DIR"
chmod 0750 "$DB_DIR"
[[ -f "$DB_DIR/users.db" ]] && { chown "root:${SVC_GROUP}" "$DB_DIR/users.db"; chmod 0640 "$DB_DIR/users.db"; }

echo "[5/5] verify"
getfacl -p "$DATA_ROOT" 2>/dev/null || true
echo
echo "服务进程请以该账户启动："
echo "  sudo -u $SVC_USER python3 server.py --config config.server.json"
echo
cat <<'UNIT'
可选：systemd 单元再叠一层内核级隔离
  [Service]
  User=filesvc
  NoNewPrivileges=yes
  ProtectSystem=strict
  ProtectHome=yes
  PrivateTmp=yes
  ReadWritePaths=/srv/securefile/data
  CapabilityBoundingSet=
  # 或进一步：RootDirectory=/srv/securefile  (等价于 chroot)
UNIT
