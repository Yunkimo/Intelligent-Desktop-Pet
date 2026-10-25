#!/usr/bin/env bash
# 首次安装；已有部署用 docs/deploy.md 的备份/升级流程，不覆盖运行目录。
# sudo bash scripts/deploy-server.sh /absolute/source --install
# bash scripts/deploy-server.sh /absolute/source --check
set -euo pipefail
REPO_DIR="${1:?用法: bash scripts/deploy-server.sh <源码绝对路径> [--check|--install]}"
MODE="${2:---check}"
APP_DIR="/home/idp/idp"
VENV="/home/idp/venvs/idp"
SERVICE="/etc/systemd/system/idp-backend.service"
SITE="/etc/nginx/sites-available/idp"
ENABLED="/etc/nginx/sites-enabled/idp"

die() { printf '拒绝：%s\n' "$*" >&2; exit 1; }
[[ "$MODE" == "--check" || "$MODE" == "--install" ]] || die "未知模式"
[[ "$REPO_DIR" == /* ]] || die "源码必须使用绝对路径"
REPO_DIR="$(cd "$REPO_DIR" && pwd -P)"
for source in backend/requirements.txt backend/.env.example backend/app/main.py \
              scripts/check_deployment.py deploy/nginx/idp.conf deploy/idp-backend.service; do
    [[ -f "$REPO_DIR/$source" ]] || die "缺少源码文件 $source"
done
for target in "$APP_DIR" "$VENV" "$SERVICE" "$SITE" "$ENABLED" /var/lib/idp /var/backups/idp; do
    [[ ! -e "$target" && ! -L "$target" ]] || die "目标已存在 $target；不会覆盖，按手册执行升级"
done
[[ ! -L /home/idp && ! -L /home/idp/venvs ]] || die "目标父目录不能是符号链接"
[[ -z "$(find "$REPO_DIR/backend" "$REPO_DIR/scripts" "$REPO_DIR/deploy" -type l -print -quit)" ]] \
    || die "源码含符号链接，请使用普通文件的源码副本"
printf '源码检查通过。首次安装目标：%s；代理先仅监听 127.0.0.1:8080。\n' "$APP_DIR"
if [[ "$MODE" == "--check" ]]; then exit 0; fi
[[ "$(id -u)" == "0" ]] || die "--install 必须由 root 执行"
trap 'echo "安装失败，保留现场。不要直接覆盖重跑；按部署手册排错。" >&2' ERR

apt-get update
apt-get install -y python3 python3-venv nginx curl rsync
if ! id -u idp >/dev/null 2>&1; then
    useradd --system --create-home --home-dir /home/idp --shell /usr/sbin/nologin idp
fi
install -d -o root -g root -m 755 "$APP_DIR"
for component in backend scripts deploy; do
    install -d -m 755 "$APP_DIR/$component"
    # 不带入来源机配置、数据库、备份或虚拟环境，也不覆盖已有目标。
    rsync -a --include='.env.example' --include='.env.integration.example' --exclude='.env*' \
        --exclude='.venv/' --exclude='data/' --exclude='backups/' \
        --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.db*' --exclude='*.log' \
        "$REPO_DIR/$component/" "$APP_DIR/$component/"
done
chown -R root:root "$APP_DIR"
find "$APP_DIR" -type d -exec chmod 755 {} +
find "$APP_DIR" -type f -exec chmod 644 {} +
install -d -o idp -g idp -m 700 /var/lib/idp /var/backups/idp
install -d -o idp -g idp -m 755 "$(dirname "$VENV")"
runuser -u idp -- python3 -m venv "$VENV"
runuser -u idp -- "$VENV/bin/python" -m pip install --disable-pip-version-check -r "$APP_DIR/backend/requirements.txt"

# 凭据只写入新配置文件，不进入命令行、输出或来源目录。
"$VENV/bin/python" - "$APP_DIR/backend" <<'PY'
import os
import secrets
import sys
from pathlib import Path
backend = Path(sys.argv[1])
text = (backend / ".env.example").read_text(encoding="utf-8")
lines = []
for line in text.splitlines():
    if line.startswith("API_TOKEN="):
        line = "API_TOKEN=" + secrets.token_hex(32)
    elif line.startswith(("LLM_API_KEY=", "LLM_BASE_URL=", "LLM_VISION_MODEL=")):
        line = line.split("=", 1)[0] + "="
    elif line.startswith("DB_PATH="):
        continue
    lines.append(line)
lines.append("DB_PATH=/var/lib/idp/pet.db")
with (backend / ".env").open("x", encoding="utf-8") as stream:
    os.chmod(backend / ".env", 0o600)
    stream.write("\n".join(lines) + "\n")
PY
chown idp:idp "$APP_DIR/backend/.env"
install -m 644 "$APP_DIR/deploy/idp-backend.service" "$SERVICE"
install -m 644 "$APP_DIR/deploy/nginx/idp.conf" "$SITE"
ln -s "$SITE" "$ENABLED"
nginx -t
systemctl daemon-reload
systemctl enable --now idp-backend
systemctl reload nginx
READY=false
for attempt in {1..30}; do
    if curl --fail --silent --max-time 2 http://127.0.0.1:8080/api/health >/dev/null; then
        READY=true
        break
    fi
    sleep 1
done
[[ "$READY" == "true" ]] || die "健康检查超时"
runuser -u idp -- "$VENV/bin/python" "$APP_DIR/scripts/check_deployment.py" \
    http://127.0.0.1:8080 --env-file "$APP_DIR/backend/.env"
echo "本机安装检查通过；尚未配置公网域名和 TLS。继续执行 docs/deploy.md。"
