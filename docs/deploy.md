# 部署手册（C4）

本手册覆盖三条路线：**本地开发**、**内网穿透演示**、**学生机部署**。每条路线列出前置、安装、启动、校验、日志、停止与回滚。后端遵守**单 worker / 单调度实例**限制（B2/B3 契约），数据库路径固定于配置，不依赖启动者当前目录。

## 0. 通用前置

- Python ≥ 3.10（本仓库 CI 验证 3.10 / 3.12）
- 仓库克隆；后端配置 `backend/.env`（复制自 `backend/.env.example`，至少填 `API_TOKEN`）
- 健康检查不是业务全链路验证：部署校验需执行 [scripts/check_deployment.py](../scripts/check_deployment.py)（健康 + 鉴权 REST + WS 握手）

## 1. 本地开发路线（Windows / Linux / macOS）

适用：开发者工具联调、功能验收。

```powershell
# Windows（自动建 venv、装依赖、缺 .env 时从示例复制）
powershell -ExecutionPolicy Bypass -File scripts\run-backend.ps1 -Port 8001 -Interval 30
```

```bash
# Linux / macOS
./scripts/run-backend.sh 8001 30
```

| 项 | 说明 |
|---|---|
| 端口 | 默认 8001（`0.0.0.0` 供局域网真机访问；仅信任网络内使用） |
| 校验 | `curl http://127.0.0.1:8001/api/health` → `{"status":"ok"}`；随后运行 `check_deployment.py` |
| 防火墙 | 真机访问需放行 TCP 8001：`netsh advfirewall firewall add rule name="IDP-backend-8001" dir=in action=allow protocol=TCP localport=8001`（管理员） |
| 日志 | 前台输出；uvicorn 日志已做 query 脱敏（见 docs/security.md） |
| 停止 | 终端 Ctrl+C |
| 重置 | 演示数据重置用 [scripts/reset_demo.py](../scripts/reset_demo.py)（只接受 `backend/data/` 下的库，自动备份） |

小程序侧：开发者工具「详情 → 本地设置 → 勾选不校验合法域名」仅限本路线调试；`config.js` 的 `baseUrl` 指向本机/局域网地址。

## 2. 内网穿透演示路线（cpolar）

适用：临时公网 HTTPS 演示（微信真机 + WSS）。**穿透即对外暴露**：执行前确认 API Key 已配置、库内无真实用户数据、日志脱敏已启用；演示结束立即关闭隧道。

| 步骤 | 操作 |
|---|---|
| 1. 注册 | [cpolar](https://www.cpolar.com/)（国内可达；也可用 ngrok，本手册以 cpolar 为例） |
| 2. 启动后端 | 先按路线 1 启动并跑通 `check_deployment.py` |
| 3. 建隧道 | 控制台或 CLI：`cpolar http 8001`（免费版域名随机变化） |
| 4. 校验 | `curl https://<你的域名>/api/health`；`check_deployment.py https://<你的域名>`（WS 校验自动走 WSS） |
| 5. 小程序 | `config.js` 的 `baseUrl` 改为 `https://<你的域名>`；真机预览 |
| 6. 收尾 | 关闭隧道进程；如需长期域名，在 cpolar 控制台绑定（需备案域名按路线 3 说明确认地区要求） |

安全注意：本项目的共享 `X-API-Key` 只适合受控演示（契约文档已声明）；公开暴露期间不要写入真实数据；穿透地址/密钥不截图、不录像。

## 3. 学生机部署路线（Ubuntu + systemd + Nginx + TLS）

适用：长期运行、绑定域名、对外提供 HTTPS/WSS。以下步骤以 Ubuntu 22.04+、非 root 服务账号 `idp`、域名 `idp.example.edu.cn` 为例。

### 3.1 前置与目录

```bash
# 以 root 执行一次
adduser --disabled-password --gecos '' idp
apt-get update && apt-get install -y python3 python3-venv nginx certbot python3-certbot-nginx ufw
ufw allow 80/tcp && ufw allow 443/tcp && ufw enable   # 只开 80/443，8001 不对公网开放
```

```bash
# 以 idp 账号执行
mkdir -p /home/idp/idp /home/idp/venvs
cd /home/idp/idp
git clone <仓库地址> .                      # 或上传代码包；记录部署 SHA
python3 -m venv /home/idp/venvs/idp
/home/idp/venvs/idp/bin/pip install -r backend/requirements.txt
cp backend/.env.example backend/.env && chmod 600 backend/.env
vi backend/.env                            # 填 API_TOKEN（openssl rand -hex 32 生成）
```

### 3.1 前置与目录

> **快速路径**： 一键完成 §3.1 与 §3.2 的全部步骤
> （依赖安装、服务账号、代码复制、venv、.env 生成、systemd、Nginx WebSocket 代理、健康检查）。
> 手工步骤保留如下，便于排错与回滚。

### 3.2 systemd 服务

`/etc/systemd/system/idp-backend.service`（root 创建）：

```ini
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
# 数据库与备份目录权限收紧
UMask=0077

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now idp-backend
systemctl status idp-backend           # Active: running
curl http://127.0.0.1:8001/api/health  # {"status":"ok"}
```

单 worker 约束见 B1/B2/B3 契约：多实例会导致调度重复领取与连接集合不可见，禁止横向扩容声称等价。

### 3.3 Nginx 反向代理 + WebSocket Upgrade + TLS

`/etc/nginx/sites-available/idp`（root 创建）：

```nginx
server {
    listen 80;
    server_name idp.example.edu.cn;

    # WebSocket Upgrade 头必须逐跳转发
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
```

```bash
ln -s /etc/nginx/sites-available/idp /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d idp.example.edu.cn      # 签发并自动续期（certbot.timer 每 12h 检查）
```

> 域名需在 ICP 备案（境内服务器）并加入微信公众平台「request/uploadFile/socket 合法域名」。地区与备案要求以实际服务器所在地和发布路线为准。

### 3.4 日志轮转

`/etc/logrotate.d/idp-backend`：

```
/home/idp/idp/backend/logs/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
}
```

（后端日志落盘路径按运行环境配置；journald 由 `journalctl -u idp-backend` 查看并按系统默认轮转。）

### 3.5 备份与恢复

```bash
# 备份（停服后执行最稳；SQLite backup 接口本身支持在线一致性复制）
systemctl stop idp-backend
cd /home/idp/idp && /home/idp/venvs/idp/bin/python scripts/backup_backend_db.py backend/data/pet.db backups/pet-$(date +%F).db
systemctl start idp-backend

# 恢复（停服 → 复制回 → 启服）
systemctl stop idp-backend
cp backups/pet-YYYY-MM-DD.db backend/data/pet.db
systemctl start idp-backend
```

迁移（如 B3 数据库版本升级）前先按上述备份，并在副本验证迁移后再上线。

### 3.6 部署校验与回滚

- 校验：`check_deployment.py https://idp.example.edu.cn`（健康 + 鉴权 REST + WSS 握手），再走一遍「后端加数据 → 小程序实时刷新」的人工用例
- 回滚：代码回退到上一部署 SHA + 数据库恢复备份（两步都做，顺序：先停服 → 恢复 DB → 回退代码 → 启服）
- 密钥：`.env` 权限 600、`UMask=0077`；轮换 = 改 `API_TOKEN` 后重启

## 4. 路线选择与限制汇总

| 路线 | 适用 | 限制 |
|---|---|---|
| 本地开发 | 日常联调 | 仅局域网；域名校验需开发者工具调试开关 |
| 内网穿透 | 短时公网演示 | 免费域名随机变化；受控演示安全边界 |
| 学生机 | 长期运行 | 需域名、备案、TLS、运维；按 3.x 全部落实 |
