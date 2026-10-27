# 部署手册（C4）

对应 [Issue #12](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/12) 的 2026-10-23 版范围：部署与运维。本次工作树为 `feat/miniprogram-c4`，基线 `f58f07b`（用户提供评审包），修复尚未提交，具体文件摘要随[复验报告](c4-verification.md)记录。阶段文档、CI 与依赖/安全总说明在 C5 交付。

目标服务器：`8.148.29.9`；域名：`shynb.beer`；预期公网入口：`https://shynb.beer`，WebSocket 为 `wss://shynb.beer/ws`。这是用户提供的部署目标，不是已上线的结论。服务器资源和服务器路线实测按 Issue 中 A/C 分工由 A 提供，C 提供脚本、配置及联调；[验收记录模板](evidence/c4/acceptance-template.md)由实际操作者填写。

用户随后说明 ICP 备案尚未通过，当前先采用[公网 IP + 开发者工具调试豁免](C4-IP调试复验.md)：入口 http://8.148.29.9:8080 已从协作电脑验证健康接口 200，经 Nginx 代理到回环后端。此路线单列为开发联调，后续仍保留正常 HTTPS/WSS 的验收；健康及负向鉴权成功不等于有效凭据业务、WS 事件或真机已通过。

## 1. 本地启动

Python 3.10+，依赖锁文件 backend/requirements.txt；小程序检查使用 Node 22.13+ 与 npm ci。命令从仓库根目录运行。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run-backend.ps1 -Port 8001
```

```bash
bash scripts/run-backend.sh 8001
```

启动器创建 venv，按 requirements 摘要判断是否重装依赖。首次缺少配置时复制 backend/.env.example 为 backend/.env 并退出 1，填写随机 API_TOKEN 后再启动。空值/示例 API_TOKEN 被拒绝；未用的 LLM_API_KEY、LLM_BASE_URL、LLM_VISION_MODEL 留空，WX_ENABLED=false。

默认监听 127.0.0.1。局域网真机测试显式使用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run-backend.ps1 -Port 8001 -Interval 1 -BindAddress 0.0.0.0
```

```bash
bash scripts/run-backend.sh 8001 1 0.0.0.0
```

仅在可信局域网按需放行端口；公网服务器不开放 8001。Ctrl+C 停止。启动失败、依赖安装失败和端口冲突返回非零；PowerShell 查看 $LASTEXITCODE，Bash 查看 $?。

配置优先级：环境变量 > backend/.env > 默认值。显式 Interval 覆盖该次扫描间隔，省略则沿用配置。启动器将相对 DB_PATH 解析到 backend，例如 DB_PATH=data/demo-c4.db；systemd 的 WorkingDirectory 也为 backend。服务器建议绝对路径。自行调用 Uvicorn 时相对路径依赖工作目录，不适用启动器的路径保证。

## 2. 七项只读自检

```powershell
backend/.venv/Scripts/python scripts/check_deployment.py http://127.0.0.1:8001
backend/.venv/Scripts/python scripts/check_deployment.py https://你的实际域名
```

Linux 使用 backend/.venv/bin/python。API_TOKEN 从 backend/.env 或环境变量读取；可用 --env-file 指定配置，不能在 URL/命令行中放凭据。

七项是：health JSON、REST 无/错误凭据 401、正确凭据 200、WS 正确凭据 101、无/错误凭据 403。HTTPS 派生 WSS，TLS/502/网络错误一律失败。不跟随重定向或环境代理；入口不接受查询参数、用户信息或片段。自建 CA 用 --ca-file ca.pem，不能关闭证书验证。

7/7 不包含写入、业务事件、图片识别和真机验收；这些按人工复验表执行。

在受控演示环境，显式选择业务联调检查：

```powershell
backend/.venv/Scripts/python scripts/check_deployment.py https://shynb.beer --exercise
```

先完成七项只读检查，再创建一条无提醒日程和一条课程，核对 REST 写入/读回、两类 WS 事件、主动断开后重连与 REST 校正，最后删除并读回确认这两条记录。完整成功为 **14/14**。不创建提醒，不触发微信或语音。默认仍是只读。

脚本不重试创建，失败时返回非零；出现超时/丢响应可能留下 `c4-check-…` 临时记录，输出本轮唯一标识供人工查找。只清理创建结果已确认且仍带本轮标识的记录；标识被改动则保留现场。服务正常接入实际数据库；在公网运行前应使用专用演示数据并告知其他客户端将短暂看到测试数据。此检查只验证脚本端主动重连，不能替代小程序断网后的自动重连、界面刷新及真机验收。

## 3. 穿透与客户端

本地检查通过后按服务官方说明建立隧道，例如 `cpolar http 8001`；记录工具版本、实际 HTTPS 地址和启动时间，并对该地址重新自检。免费临时地址重建后可能变化，需同时更新客户端地址并重新编译/预览。通过 Ctrl+C 关闭本次前台隧道和后端；不要删除或停止无关服务。隧道域名能否配置到微信后台，以当前账号实际结果为准，未配置成功则只算调试路线。

小程序从 `config.example.js` 复制 `config.js`，填写 `baseUrl: 'https://shynb.beer'`（末尾不带 `/`）和后端相同的 `apiKey`；桌宠配置同一地址与 API Key。小程序现有 REST、上传和 WS 适配均从这一个 baseUrl 派生，不要在页面另写地址。

| 客户端能力 | 本项目目标地址 | 微信后台核对 |
|---|---|---|
| wx.request | https://shynb.beer/api/... | request 合法域名 https://shynb.beer |
| wx.uploadFile | https://shynb.beer/api/courses/parse-image | uploadFile 合法域名 https://shynb.beer |
| wx.connectSocket | wss://shynb.beer/ws | socket 合法域名 wss://shynb.beer |

普通 HTTPS 可访问不代表小程序允许访问。开发工具“不校验合法域名”仅为调试条件；体验版/正式路线须正常校验。使用你自己的 AppID，并记录开发版/体验版、微信版本、基础库和校验条件。C4 不要求先发布正式版才能联调，但正常域名/证书校验下的结果必须单列。

演示结束关闭隧道。共享 API Key 只适用于受控演示，不是多用户隔离。不要使用真实用户数据或公开含凭据 URL。历史实测按原版本留存；本轮按新的验收记录重新核对，不借用过去记录判定通过。

## 4. 学生机首次安装（Ubuntu 22.04+ 模板）

需要有管理权限的测试服务器。上传当前待验源码，不携带本机 .env、数据库、备份或虚拟环境。本轮没有执行真实 Ubuntu/systemd 安装。

```bash
bash /absolute/source/scripts/deploy-server.sh /absolute/source --check
sudo bash /absolute/source/scripts/deploy-server.sh /absolute/source --install
```

默认 --check 只检查。首次安装在 apt/复制前拒绝已有应用、venv、数据目录、服务或 Nginx 站点，不会升级已有部署。中断后保留现场，按失败步骤排查，不直接删目录重跑。

| 内容 | 路径及权限 |
|---|---|
| 代码 | /home/idp/idp，root 管理 |
| venv | /home/idp/venvs/idp，idp 安装依赖 |
| 配置 | /home/idp/idp/backend/.env，idp:600 |
| 数据 | /var/lib/idp/pet.db，目录 idp:700 |
| 备份 | /var/backups/idp，目录 idp:700 |
| systemd | [服务模板](../deploy/idp-backend.service)，单 worker、无 reload、UMask=0077 |
| Nginx | [代理模板](../deploy/nginx/idp.conf)，初始仅监听 127.0.0.1:8080 |

只复制 backend/scripts/deploy，排除来源 .env、数据、备份、venv、日志，拒绝符号链接来源。生成新随机 API_TOKEN，清空外部模型凭据，不回显密钥。不删除其他 Nginx 站点，不修改防火墙。

```bash
sudo systemctl status idp-backend
sudo journalctl -u idp-backend -n 100 --no-pager
curl --fail http://127.0.0.1:8080/api/health
sudo -u idp /home/idp/venvs/idp/bin/python /home/idp/idp/scripts/check_deployment.py http://127.0.0.1:8080
```

### 4.1 域名与 TLS

1. 核对域名、DNS、地区与平台要求；保留 SSH 管理端口，按需开放 80/443，不开放后端 8001。
2. 备份 /etc/nginx/sites-available/idp。将 listen 127.0.0.1:8080 改为 listen 80，将 server_name 改为自己的域名；保留其他代理配置。执行 sudo nginx -t 和 sudo systemctl reload nginx。此阶段不进行携带凭据的公网请求。
3. 安装 certbot、python3-certbot-nginx，执行 sudo certbot --nginx --redirect -d 你的域名。失败则恢复本机监听，不继续宣称上线。
4. 检查 HTTP 跳转、HTTPS 证书链，并确认 Certbot 修改后的 HTTPS server 仍包含 idp_safe 日志、error_log、11m 上传上限和 Upgrade 配置。运行 HTTPS 七项自检。
5. 执行 sudo certbot renew --dry-run，用 systemctl list-timers 核实实际续期任务；不能只凭安装成功假定续期可用。
6. 从另一网络和正常合法域名校验下的微信真机验证读写、WSS、断网恢复及图片上传。

服务器已安装过后端时，不再执行首次安装脚本。先用以下只读命令核对实际服务路径、端口和版本；避免输出 EnvironmentFile 内容或含 token 的连接地址：

```bash
sudo systemctl show idp-backend -p ActiveState -p SubState -p MainPID -p WorkingDirectory -p ExecStart
sudo ss -lntp '( sport = :80 or sport = :443 or sport = :8001 )'
curl --fail --max-time 10 https://shynb.beer/api/health
```

服务名/安装目录若与模板不同，先记录差异，再替换手册命令中的实际值。源码 SHA 从上传前的干净源码目录 `git rev-parse HEAD` 记录；未提交源码还需保存文件摘要，单独记录 HEAD 不足以识别部署版本。ZIP 没有 Git 历史时记录包的 SHA256 和部署文件摘要。升级到独立目录、单独建立 venv，停服备份后切换服务路径；不要向旧工作树直接覆盖文件。

访问日志只保留方法、无查询参数的路径、状态和耗时。Nginx 原生错误日志可能包含完整请求行，不能按 log_format 脱敏，所以本站点 error_log 写 /dev/null。用脱敏 access 的 status/upstream_status 和后端 journal 排错；这是有意减少诊断信息。共享网关、默认站点和隧道平台日志须另行核查，不能声称全链路已自动脱敏。

请求体上限 11 MiB，覆盖后端 10 MiB 图片加 multipart 开销。大于 1 MiB 的有效图片应到达后端。未配置视觉模型时 503 只证明传输通过，不能算识别通过。

依据：[Nginx WebSocket](https://nginx.org/en/docs/http/websocket.html)、[Nginx 日志](https://nginx.org/en/docs/http/ngx_http_log_module.html)、[请求体限制](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size)、[Certbot](https://eff-certbot.readthedocs.io/en/stable/using.html#nginx)及[微信网络能力](https://developers.weixin.qq.com/miniprogram/dev/framework/ability/network.html)。2026-10-24 核对 Nginx/Certbot 官方说明；微信文档读取失败，实际账号/域名能力须在后台核验。

### 4.2 启停与日志

使用 systemctl stop/start/restart idp-backend、journalctl -u idp-backend 和 ss -lntp 定位进程与端口。一个数据库只运行一个后端实例；多个端口各一个 worker 仍是多个调度实例。systemd 已运行时不要再启动本地脚本。

Nginx 日志轮转沿用发行版 /etc/logrotate.d/nginx，确认覆盖 idp-access.log；后端输出到 journald，不把不存在的 backend/logs 当作已启用日志。

### 4.3 故障排查

| 现象 | 检查顺序 |
|---|---|
| 域名无法解析 | 在电脑及手机网络查询 shynb.beer 的 A 记录是否为 8.148.29.9；同时检查 www 子域是否单独配置；确认实际使用的域名与证书一致 |
| HTTPS 失败 | DNS → 安全组/防火墙 443 → Nginx 监听 → 证书有效期、SAN 与完整证书链；不要以关闭校验作为修复 |
| 502 | systemctl status 和 journalctl → 回环 8001 健康检查 → Nginx upstream 地址；自检不能把 502 误认为鉴权通过 |
| REST 401 | 客户端和实际后端配置的 API_TOKEN 是否一致、请求头是否携带；不在截图/命令输出公开密钥 |
| 普通 HTTP 可用而 WS 失败 | 检查 wss 协议、socket 域名、Upgrade/Connection 头、101 握手、代理超时；断网恢复后 REST 重新拉取 |
| 图片 413/503/504 | 413 检查代理 11m 与后端图片 10 MiB；503 检查后端视觉模型配置；504 检查上游耗时；到达后端不等于识别成功 |
| 手机 request:fail | 不把手机 127.0.0.1 当电脑地址；先手机浏览器健康检查，再核对微信三类合法域名、TLS、网络、防火墙、当前 config.js 是否已重新编译上传 |
| 重启后数据丢失 | 比较实际 DB_PATH、WorkingDirectory、运行用户权限；查是否错误启动了第二份后端或指向了新库 |

日志查询以脱敏 access 状态与后端 journal 为主。先核查日志是否已脱敏，再导出必要片段；不要直接发布完整 nginx -T、.env、系统环境或带 token 的 WS URL。

## 5. 备份、恢复与版本回滚

先记录代码版本、依赖锁、DB_PATH、`PRAGMA user_version`、`schema_migrations` 表和实际表列。本项目不能只看 user_version：B2/B3 的实际迁移记录在 schema_migrations。下面假定服务器使用 /var/lib/idp/pet.db；与实际不一致时须替换。

```bash
# 先建目录并确认权限，再停服；备份失败则停止后续维护步骤
sudo install -d -o idp -g idp -m 700 /var/backups/idp
sudo systemctl stop idp-backend
sudo -u idp /home/idp/venvs/idp/bin/python /home/idp/idp/scripts/backup_backend_db.py /var/lib/idp/pet.db /var/backups/idp/pet-唯一时间戳.db
sudo systemctl start idp-backend
```

备份脚本拒绝覆盖已有目标，并执行 SQLite 完整性检查。恢复到新路径，保留原库与 sidecar，避免把旧 WAL 套入恢复文件：

```bash
sudo systemctl stop idp-backend
sudo -u idp /home/idp/venvs/idp/bin/python /home/idp/idp/scripts/backup_backend_db.py /var/backups/idp/pet-唯一时间戳.db /var/lib/idp/restored-唯一时间戳.db
# 将 backend/.env 的 DB_PATH 改为新恢复副本，再启动读回业务数据
sudo systemctl start idp-backend
```

代码回滚必须同时准备“上一版本代码 + 对应依赖 + 迁移前备份”。停服并保存当前配置/数据副本，将服务 WorkingDirectory、EnvironmentFile、ExecStart 切到独立的旧版本目录及其 venv，DB_PATH 指向恢复副本；daemon-reload 后启动检查。不要在有改动的工作树上 reset/checkout，也不要让旧代码读取新 schema。备份后的写入可能丢失，先导出核对。

本地提供真实历史代码回滚测试：`tests_deployment/test_version_rollback.py`，旧版本 `5ff462f` 的 B2 schema 1 → 当前 B3 schema 1/2 → 恢复迁移前备份后用旧代码启动，核对旧业务记录保留、备份后的新写入不在恢复副本中、升级后原库仍在。它在临时发布目录运行，不替代 Ubuntu/systemd 切换和目标服务器当前 schema 的演练；正式升级必须先在实际版本副本上验证。

## 6. 演示库重置

不再默认读取 DB_PATH 或 pet.db；必须显式选择 backend/data/demo-名称.db。

```powershell
backend/.venv/Scripts/python scripts/reset_demo.py --database backend/data/demo-c4.db --init
# 设置 backend/.env：DB_PATH=data/demo-c4.db，再启动
# 重置前 Ctrl+C 停止所有使用该库的服务
backend/.venv/Scripts/python scripts/reset_demo.py --database backend/data/demo-c4.db
backend/.venv/Scripts/python scripts/reset_demo.py --database backend/data/demo-c4.db --yes --stopped
```

--init 只能初始化不存在的库，不能给普通旧库补标记。默认只预览；执行需 --yes --stopped。--stopped 是操作者确认，不是自动探测所有进程。WAL/SHM/journal 或锁冲突时拒绝，不自动删除。先备份到 backend/backups，再替换为空的带标记库；失败保留原库及诊断备份。恢复到新路径，按上一节校验。

## 7. 本地复现与验收边界

```powershell
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
backend/.venv/Scripts/python -m pytest tests_deployment -o addopts='' -q
backend/.venv/Scripts/python -m ruff check scripts tests_deployment
backend/.venv/Scripts/python scripts/check_c4_docs.py
```

本地代理/TLS 测试需 NGINX_BINARY、OPENSSL_BINARY 指向可执行文件，或将工具加入 PATH；历史版本回滚还需完整 Git 历史中的 5ff462f。缺失会 skip，不能算通过。只读自检不会发微信；测试使用临时 DB、随机凭据和回环端口，显式关闭微信/模型调用。

人工确认前不 commit。本次 C4 不修改 CI、阶段文档和依赖/安全总说明，按 Issue #12 当前七项验收记录部署事实；相关后续工作在 C5 归属，避免重复计分。完整结果、实际环境和待测项见[复验报告](c4-verification.md)。
