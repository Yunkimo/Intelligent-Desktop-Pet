#!/usr/bin/env bash
# 学生机/服务器一键部署脚本（Ubuntu 22.04+，root 执行）。
# 完成：系统依赖、非 root 服务账号、代码复制、虚拟环境、依赖安装、
#       生成 .env（随机 API_TOKEN）、systemd 服务、Nginx 反向代理（含 WebSocket Upgrade）。
# 用法：
#   1) 把仓库代码上传到服务器任意目录（如 /root/IDP）
#   2) sudo bash /root/IDP/scripts/deploy-server.sh /root/IDP
#   3) 记录部署 SHA：git -C /root/IDP rev-parse HEAD（或上传前本地记录）
# 域名/HTTPS/备案在备案通过后另行配置（见 docs/deploy.md §3.3）。
set -euo pipefail

REPO_DIR="${1:?用法: sudo bash scripts/deploy-server.sh <仓库目录绝对路径>}"
SERVICE_USER="idp"
APP_DIR="/home/${SERVICE_USER}/idp"
VENV="/home/${SERVICE_USER}/venvs/idp"

echo "==> 1/8 安装系统依赖"
apt-get update -y
apt-get install -y python3 python3-venv nginx curl

echo "==> 2/8 创建服务账号 ${SERVICE_USER}（已存在则跳过）"
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    useradd --system --create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

echo "==> 3/8 复制代码到 ${APP_DIR}"
mkdir -p "${APP_DIR}"
cp -r "${REPO_DIR}/." "${APP_DIR}/"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"

echo "==> 4/8 创建虚拟环境并安装依赖"
if [ ! -x "${VENV}/bin/python" ]; then
    python3 -m venv "${VENV}"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "$(dirname "${VENV}")"
fi
"${VENV}/bin/pip" install --disable-pip-version-check -q -r "${APP_DIR}/backend/requirements.txt"

echo "==> 5/8 生成 backend/.env（已存在则不覆盖）"
if [ ! -f "${APP_DIR}/backend/.env" ]; then
    cp "${APP_DIR}/backend/.env.example" "${APP_DIR}/backend/.env"
    TOKEN="$("${VENV}/bin/python" -c 'import secrets; print(secrets.token_hex(16))')"
    sed -i "s/^API_TOKEN=.*/API_TOKEN=${TOKEN}/" "${APP_DIR}/backend/.env"
    echo "    已生成随机 API_TOKEN（记录于 backend/.env，客户端 config.js 需填同一值）"
else
    echo "    backend/.env 已存在，保持原样"
fi
chmod 600 "${APP_DIR}/backend/.env"
chown "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}/backend/.env"

echo "==> 6/8 安装 systemd 服务"
cat > /etc/systemd/system/idp-backend.service <<'UNIT'
[Unit]
Description=IDP backend (single worker)
After=network.target

[Service]
User=idp
WorkingDirectory=/home/idp/idp/backend
EnvironmentFile=/home/idp/idp/backend/.env
ExecStart=/home/idp/venvs/idp/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now idp-backend

echo "==> 7/8 配置 Nginx（含 WebSocket Upgrade；server_name 待域名解析后由 certbot 填写）"
cat > /etc/nginx/sites-available/idp <<'NGINX'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/idp /etc/nginx/sites-enabled/idp
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "==> 8/8 健康检查"
sleep 2
curl -sf http://127.0.0.1:8001/api/health
echo
echo "部署完成。后端状态: systemctl status idp-backend"
echo "提醒：视觉识别（LLM_*）与微信订阅（WX_*）需按需补充 backend/.env；"
echo "域名解析 + certbot HTTPS 见 docs/deploy.md §3.3。"
