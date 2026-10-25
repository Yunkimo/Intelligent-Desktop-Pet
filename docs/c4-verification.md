# C4 部署实现与复验记录（更新至 2026-10-25）

依据 [Issue #12](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/12) 2026-10-23 版范围：部署与运维。阶段文档、CI、依赖/安全总说明归 C5；同步 develop 时只处理既有 CI 的合并冲突并保留原有检查。本轮没有修改 Issue 或创建提交。

## 本次交付范围

当前提交交付部署工具、服务/代理模板、自动复验脚本及脱敏验收记录，并保留合入develop 9bca38f的兼容结果。IP开发调试路线已通过：手机/开发者工具读写与断网恢复、桌宠气泡语音、5次到期展示（含时钟误差上界最大2.069秒）、真实模型与界面课表图片导入/编辑/删除、服务重启持久化、备份恢复及ECS隔离历史版本/schema回滚。测试记录已清理。

正式HTTPS/WSS及关闭调试豁免后的真机验收按用户最新要求暂缓，另一成员独立复现尚未完成，不关闭Issue #12。后文“未commit/push”、基线HEAD及未提交工作树字段描述验收采样时点；交付提交和远程推送状态以Git历史为准。服务器仍是当时核验的d418655，本机提交/推送不等于更新服务器。

## 被测对象

- 分支：`feat/miniprogram-c4`，工作树 `D:\IDP\worktrees\c4-review-package-20261024`。
- 原始基线：`f58f07bcea103029e45dded7db014713f1ea9b98`，与用户提供的 C4 评审包中 220 个原有文件完全一致；另有 4 个 C3 文件的原始副本已随同步前备份保留，后续工作树使用 develop 的 C3 版本。
- 当前为原始基线合入 `origin/develop` 的 `9bca38f`，再恢复未提交部署修复；合并尚未 commit。环境与范围见 [source-manifest.json](evidence/c4/source-manifest.json)，文件摘要见 [source-checksums.sha256](evidence/c4/source-checksums.sha256)、[输入包摘要](evidence/c4/input-package.sha256)，不能只拿 HEAD 当作本轮修复版本；[版本记录](evidence/c4/develop-sync-version.txt)包含两个父版本。
- 复用本机既有 C4 部署修复（旧工作树保留），只迁入部署脚本、配置及部署回归；不迁入其阶段文档或 CI 改动。
- 目标服务器/域名：`8.148.29.9` / `shynb.beer`。用户明确选择自行执行服务器步骤，本轮未登录或改动服务器。

## 实现与修复

| 问题 | 本轮交付 |
|---|---|
| HTTPS 自检误用 ws，异常被当鉴权通过 | 按协议派生 WSS；REST 200/401、真实 WS 101、完整 Upgrade 拒绝 403 分别检查；TLS、502 和网络错误必须失败 |
| 只检查健康和读接口，缺少可复现业务验收 | 默认七项只读；显式 --exercise 验证两类临时业务写入/读回、真实 WS 事件、重连与 REST 校正、清理及清理后读回，完整 14/14 |
| 超时可能重复创建或误删数据 | 不重试创建；输出本轮唯一 c4-check 标识；只清理创建结果确认且仍带本轮标识的记录；事件失败仍清理已确认数据，原有记录不受影响 |
| Windows 启动失败码、路径或依赖漂移 | 返回 venv/pip/Uvicorn 失败码；相对 DB_PATH 固定按 backend 解析；requirements 摘要变化重新安装；默认回环；哈希改用 Python，适配缺少 Get-FileHash 的 PowerShell 环境 |
| 代理上传默认上限过小、日志泄露 query | Nginx Upgrade、11 MiB 请求体上限、无 query 的 access；原生请求错误日志停用，以脱敏状态和 journal 排错；保留诊断代价说明 |
| 一键脚本可能覆盖部署、携带私有文件 | 默认只检查；首次安装拒绝既有目录/服务/站点；过滤 .env*（保留示例）、数据、备份、venv 和日志；随机新凭据不回显；单 worker、回环监听 |
| 普通 pet.db 可被重置、恢复不明确 | 专用 demo-*.db、一次性初始化标记、默认预览、显式停服确认、sidecar 拒绝、先备份后替换；恢复到新路径保留原库 |
| 缺少真实版本/schema 回滚验证 | 历史 B2 代码 5ff462f 的 schema 1 → 当前 B3 schema 1/2 → 迁移前备份恢复并用旧代码启动；核对丢失的新写入范围及升级原库保留 |
| 旧 C4 全量包会覆盖较新的 C3 | 服务器交付采用工具覆盖包，不携带旧后端业务源码；额外用本地 origin/develop 的后端验证同一套部署工具 14/14 |

## 本轮实际验证

环境：Windows / Python 3.13.0；复用旧 C4 venv 中已安装的后端测试依赖（Uvicorn 0.54.0、httpx 0.28.1）。Nginx 1.30.6、OpenSSL 3.5.7；临时 CA、随机测试凭据、临时数据库、回环端口，显式关闭微信和模型调用。未使用真实数据。

- [完整部署回归](evidence/c4/deployment-tests.txt)：**26 passed，0 skipped，120.98 秒**。[JUnit 明细](evidence/c4/deployment-tests.xml)含历史回滚及 develop 后端 SHA。
- 实际通过：HTTP 与可信自建 CA 的 HTTPS、自检拒绝不可信证书、正确/缺失/错误凭据、端口不通及代理 502 失败判断、真实 task/course 事件、主动断开重连、业务清理、事件失败后清理、端口冲突非零、含空格路径、非法扫描间隔、重启数据持久化、单条 pc 到期 WS 收包、演示库保护与备份恢复。
- 真实 Nginx 同时跑 HTTP/HTTPS：约 1.9 MB 的有效 PNG 穿过代理，到达未配置模型时的 503；12 MiB 请求被 413 拒绝；101/413/502 后检查代理日志无 query token。这不是实际模型识别验收。
- 真实历史版本回滚：5ff462f 的 schema_migrations=[1]；当前基线升级为 [1,2] 并增加 wechat_user_id；迁移前副本恢复后旧代码可读原记录，备份后的新增记录不在副本中，升级后原库仍保留。
- 部署工具连接当前本地远端跟踪版本 `origin/develop`（`9cdeea21add38609f182ae4dfa0ed5b7a983cf8f`）的真实后端，14/14 通过。该结果是协议兼容验证，不表示把 develop 合入了本分支或部署到了服务器。
- Ruff 全仓检查及 **123 个 Python 文件格式检查**通过；Bash 语法、部署文档文件链接和密钥扫描结果见 [静态检查](evidence/c4/static-checks.txt)。暂存区为空。

复现命令（仓库根目录）：

```powershell
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
# NGINX_BINARY / OPENSSL_BINARY 需指向本机实际工具
backend/.venv/Scripts/python -m pytest tests_deployment -o addopts='' -o junit_family=legacy -q
backend/.venv/Scripts/python -m ruff check .
backend/.venv/Scripts/python -m ruff format --check .
backend/.venv/Scripts/python scripts/check_c4_docs.py
```

历史版本用例需完整 Git 对象；缺工具或历史时会跳过，不能据此写成全通过。本轮实际没有跳过。受 Windows 测试沙箱影响，最终在正常本机进程环境运行，用 D:/IDP/reviews/c4-20261024 下的专用临时目录；不要求用户复现同一绝对路径。

## 失败与修正

首次测试因沙箱临时目录权限失败；首次显式临时路径又缺少父目录，创建父目录后修复。Bash/OpenSSL 在执行沙箱内无法启动，改在正常本机环境运行。以上是测试环境问题，未把它们算为产品通过。

实际复验发现 Windows 启动器依赖 Get-FileHash，在本次 PowerShell 环境中缺失，改由已有 Python 计算摘要后通过。历史版本夹具最初错误选择无 B2 迁移的 1a16faf，改为真实 B2 提交 5ff462f 后验证 schema 变化。

直接 Uvicorn TLS 的负向 WS 检查出现间歇超时，服务日志有 Windows Proactor 的连接重置异常。试用另一 WS 实现没有消除问题，未保留该尝试的部署配置。负向鉴权改为完整 RFC 6455 Upgrade 请求读取 403，正常连接仍用真正 WebSocket 验证 101/事件/重连；定向 TLS 与最终完整回归通过。密钥扫描首次将 JSON 内的文件摘要误报为高熵秘密；核对均为本地计算的代码/输入包校验值，改为标准 sha256sum 清单，未关闭扫描或扩大排除范围。失败原始记录存放在本地 D:/IDP/reviews/c4-20261024，最终结果单独保留。

## 对照 Issue #12 的七项验收

| 项 | 本轮证据与实际边界 |
|---|---|
| 1 公网 HTTP | 正确 IP 8.148.29.9:8080 的有效凭据 CRUD 与鉴权通过；原错误 IP 探测保留为历史记录；正式域名路线暂缓 |
| 2 公网 WS | 真实公网 WS 101、两类事件、主动重连与 REST 校正通过；手机离线期间新增数据在恢复后自动补齐，随后新数据也自动刷新，已人工观察 |
| 3 微信真机 | IP 开发调试路线下，手机日程/课程 CRUD 已有人工操作及云端核对，测试记录已删除；上传拒绝边界 3/3 通过；真实识别返回 502，模型 Key 配置按用户要求暂缓；正常校验路线待验 |
| 4 启停持久化 | 真实服务器 systemd 重启、开机启动配置、重启后数据与 WS 通过；合并新版桌宠实际气泡/语音已人工通过，无重复；线上版本 d418655、干净工作区、唯一匹配 Python 主进程已由服务器输出确认，筛选范围见进程记录 |
| 5 备份回滚 | 真实服务器备份及恢复副本完整性、结构和记录条数一致；本地历史 B2→B3 schema 回滚通过；目标服务器历史代码/schema 隔离演练已通过；实际生产发布切换未执行 |
| 6 另一成员复现 | 已交付可操作说明与记录表，尚未由另一成员独立执行 |
| 7 独立边界 | 只交付部署运维；C5 内容不作为本项前置，也未计入本轮。其余人工项如实保留 |

因此当前结论是：**C4 部署实现、本地自动复验、云端 HTTP/WS 业务与部分服务器运维验证已完成；微信界面/真机、桌宠展示、正式路线及另一成员复现仍有待验项，不能关闭 Issue #12 或标记整项通过。**

下一步：[服务器操作](C4-服务器操作.md) → [人工复验](C4-人工复验.md) → [填写验收记录](evidence/c4/acceptance-template.md)。按用户既有要求，人工结果确认后再 commit。

## 后续：先走 IP 调试路线

2026-10-24 用户说明 ICP 备案未通过，改先使用微信开发者工具“不校验合法域名”的调试方式。新增 [IP 调试步骤](C4-IP调试复验.md)及无真实凭据的 [config.server-debug.example.js](../miniprogram/config.server-debug.example.js)，计划入口 http://8.148.29.9:8080，经 Nginx 访问回环后端。既有本地配置文件未被覆盖，实际微信开关需用户在工具中操作。

22:21（北京时间）的[只读探测](evidence/c4/debug-ip-probe.json)中，8080/8001 均连接超时。尚未连接服务器、未执行微信工具/真机操作，调试路线不能标记通过。此方式只豁免客户端调试校验，HTTPS/WSS 及正常校验下正式路线仍保留待验。

本次后续只更新配置示例、操作文档及文档检查范围；部署检查和后端逻辑未变，26 项是前述部署实现的测试记录，没有为文档修改重复运行。新增示例通过 Node 语法检查；文档链接、文件校验和密钥扫描另行核对并记录。

## 后续：服务器本地回查与独立调试入口

用户提供的服务器输出确认：2026-10-24 22:34 左右（北京时间），127.0.0.1:8001 /api/health 为 HTTP 200；127.0.0.1:8080 拒绝连接；ss 显示 Nginx 仅监听 80/443，后端仅回环 8001。原因已缩小到尚未配置调试入口，不需要先改小程序业务代码。

新增 deploy/nginx/idp-debug-8080.conf，复用原已测代理配置，改为独立 8080 监听及独立日志格式/变量名，避免与原站点重名。该模板经本地真实 Nginx -t 通过；实际服务器仍由用户安装、重载及放行端口，尚无公网成功结果。本次没有为简单配置变化重复运行原 26 项部署回归。

## 后续：公网 IP 核对与健康接口打通

2026-10-24 23:32（北京时间），用户实例截图确认实际公网 IP 为 `8.148.29.9`，此前提供并用于排查的 `8.148.31.9` 不是该目标。原 public-probe.json / debug-ip-probe.json 保持原样，其中旧 IP 的超时不能作为实际服务器不可达的证据；原域名探测仍只是当时的历史结果，当前 DNS、ICP备案和 HTTPS 状态需另行核验。

从协作电脑直连 `http://8.148.29.9:8080/api/health`，实际返回 HTTP 200 和 `status:ok`，见[本次原始结果](evidence/c4/corrected-ip-health.txt)。已修正操作文档、调试配置示例及 Nginx server_name。本次仅证明公网 HTTP 健康接口可达；有效凭据读写、WS、正式 HTTPS/WSS、微信工具及真机、另一成员复现均未据此标记通过，未登录或修改服务器。

## 后续：公网负向鉴权、域名与小程序逻辑检查

2026-10-24 继续复验：从协作电脑直连正确 IP 的 HTTP 8080，健康 JSON、课表/日程各自缺失及错误 Key 的 401、完整 WS Upgrade 缺失及错误 token 的 403，共 7/7 通过，见[负向检查](evidence/c4/public-negative-checks.json)。这组七项不同于 check_deployment.py 的默认七项：未使用真实服务器凭据，没有正确凭据 REST/WS 验证，也未创建任何业务数据。

对实际 IP 使用 --resolve 保留 shynb.beer 的 SNI/Host 和严格证书校验，HTTPS 健康接口返回 200/status:ok；HTTP 80 返回 Beaver 的备案拦截页 403。电脑 DNS 及 dns19.hichina.com 查询未返回根域名 A 地址，见[域名结果](evidence/c4/corrected-domain-probe.json)。--resolve 不属于正常域名解析成功；ICP备案、普通 DNS、微信合法域名和正式 WSS 仍待核验。

C4 评审包现有 node tests/run-tests.js 的 1 个 WS 逻辑文件、7 项通过，见[结果摘要](evidence/c4/mini-ws-logic.txt)。这是 Mock wx/定时器的适配层测试，不是手机或开发者工具操作，也不是完整 C3 订阅测试。该包前端基线较旧，后续人工界面复验沿用用户已验过的 C3 项目，不以旧 C4 包覆盖其业务代码。

该阶段创建了被 Git 忽略的本机 miniprogram/config.js；当时 apiKey 为占位值，正向业务待验。后续用户已在本机配置真实服务器凭据，结果如下。没有打印或归档真实密钥。

## 10 月 25 日：云端业务、重启与备份副本结果

当前开发调试入口为 http://8.148.29.9:8080。使用本机私有配置中的服务器凭据完成[默认自检及业务 14/14、补充修改及清理 4/4](evidence/c4/public-authenticated-checks.json)：日程与课程写入、读回、实际 WS 事件、主动断开重连和 REST 校正均通过。本轮确认创建的临时记录已清理；没有用重试 POST 制造重复记录。这些结果不代表微信界面的自动刷新或手机自动重连已经通过。

[上传拒绝边界 3/3](evidence/c4/public-upload-boundaries.json)通过：空文件 422、10.5 MiB 文件由后端返回 JSON 413、12 MiB 请求由 Nginx 返回 HTML 413。另用 1,154,843 字节的合成课表图片请求识别，得到 [502 失败结果](evidence/c4/public-image-recognition-initial-failure.json)。[只读诊断](evidence/c4/server-vision-config-diagnostic.json)确认视觉 Key 仍为示例值，用户已明确暂缓配置及识别验证，等其通知再继续；不能将拒绝边界或请求到达后端当作识别成功。

用户执行真实 systemd 重启，PID 从 59473 变为 62174，状态 active/running、UnitFileState=enabled、回环健康 200。协作电脑确认[重启前后临时数据保留、重启后 WS 101、临时数据清理](evidence/c4/server-restart-persistence.json)均通过。实际 DB_PATH 为 /home/idp/idp/backend/data/pet.db，扫描间隔 30 秒；服务状态及监听证据见[服务记录](evidence/c4/server-service-check.txt)。这是服务重启验证，未执行操作系统重启，也不代替桌宠实际气泡/语音观察。

用户还在服务器私有目录 /root/c4-backup-check.B2m4bZ 完成[备份恢复副本演练](evidence/c4/server-backup-restore.json)：备份及恢复副本完整性、结构一致、记录条数一致共四项为 true。线上库未替换、服务未因此停止；不算实际应用版本或 schema 回滚。

正式路线保留失败证据：[Python/OpenSSL 定向解析下 HTTPS/WSS 检查 0/7](evidence/c4/tls-wss-with-dns-override.json)，[客户端差异摘要](evidence/c4/tls-client-difference.txt)记录与原生 Windows curl/Schannel 的健康 200 不一致，原因未定。用户随后配置根域名 A 记录，尚未复核解析传播；按用户纠正的优先级，当前暂停正式域名排查，继续 IP 加开发调试开关路线。不能写成正式 HTTPS/WSS 已通过。

用户确认微信开发者工具当前项目为 D:/IDP/worktrees/c3-subscription/miniprogram。仅更新其被 Git 忽略的 config.js，设定云端地址并复用已验证的服务器凭据；JS 语法验证通过，其他字段及业务源码保留。用户开启开发调试设置并重新编译后确认页面正常加载，见[界面加载记录](evidence/c4/wechat-devtools-load.json)。随后协作电脑创建无提醒日程 C4-refresh-1ffddd87，用户确认停留在“今日”页、未下拉刷新或切换页面即自动出现；已按 ID 和唯一标记清理并读回确认，见[刷新及清理记录](evidence/c4/ui-refresh-1ffddd87.json)。这是开发者工具的实际界面观察，手机运行时仍待验。下一步核验界面 CRUD 和手机同 Wi-Fi 下的断网恢复。8080 安全组当前只放行公网来源 120.227.60.160，手机流量出口不能假设在白名单中。

本次只同步说明、已有运行证据和校验清单，不重复运行已通过的 26 项部署回归。人工验收模板保持未填写；未暂存、commit、push 或关闭 Issue。

后续人工日程首次核验出现[状态不一致](evidence/c4/manual-ui-tasks-initial-mismatch.json)：约定标题与今日截止日期存在，done=0，且 remind_at 非空；用户下拉刷新后也显示未完成和提醒。随后用户询问复选框用途，确认它表示完成、删除使用独立按钮。用户明确清除提醒并点击完成后，刷新仍勾选且无提醒，协作电脑再次[云端读回](evidence/c4/manual-ui-tasks.json)确认 done=1、remind_at=null，标题与截止日期保留。创建、改名、完成状态和清除提醒的保存结果通过；随后用户通过界面删除日程，云端确认原 ID 和约定标题均不存在，删除通过。本序列未修改产品源码，不据首次操作结果认定代码缺陷。

用户通过课表页新建课程后，修改名称为 C4-手工课程1025-已修改、地点为 C4-test-room，协作电脑[云端读回](evidence/c4/manual-ui-courses.json)确认保存成功。随后用户在课表页删除测试课程，云端确认原 ID3 与约定名称均不存在，课程删除通过。至此开发者工具日程、课程的新增/修改/删除均有人工操作及云端读回证据，日程完成状态也已核对。上述 CRUD 结果不代表手机 CRUD 或正式域名路线通过。

用户随后确认手机能正常加载小程序，见[手机运行记录](evidence/c4/phone-runtime.json)。按同 Wi-Fi 和 IP 调试路线，用户确认关闭手机 Wi-Fi/移动数据并回到今日页后，协作电脑创建无提醒日程 C4-refresh-a52636d8；恢复原 Wi-Fi 后，用户确认无需下拉或重开即自动出现，见[离线补齐记录](evidence/c4/ui-refresh-a52636d8.json)。随后在恢复联网并停留页面时再新增 C4-refresh-21561f33，用户确认新记录也自动出现，见[恢复后实时刷新记录](evidence/c4/ui-refresh-21561f33.json)。两条均按保存 ID 和唯一标记清理并读回确认。手机断网恢复的数据补齐及其后实时更新已有实际界面观察支持；没有测量精确恢复耗时，也未采集手机 WS 协议日志。手机直接 CRUD 后续也已通过：日程新增、改名、截止日期、完成状态及无提醒均已读回；课程新增、改名和地点均已读回；用户从手机删除后，云端确认两条 ID 均不存在，见[手机日程记录](evidence/c4/manual-phone-tasks.json)和[手机课程记录](evidence/c4/manual-phone-courses.json)。

## 同步 develop 后的复验（2026-10-25）

用户要求先同步 GitHub develop，再继续 C4。已 fetch 到 9bca38f，并以 --no-commit 合并到当前 C4 工作树。同步前对 71 个非忽略改动文件逐一校验备份，7 个跟踪文件的部署修复随后以三方方式恢复；4 个原输入包 C3 额外文件保存在备份中，工作树改用 develop 的版本。私有 config.js 保留且未纳入备份包或提交。

五处冲突为 .github/workflows/ci.yml、README.md、小程序的 package.json / package-lock.json / eslint.config.js。CI 保留 develop 的 C3 集成检查，npm test 入口同时运行原 WS 逻辑与 C3 订阅逻辑；依赖锁采用 develop 的 ESLint 10.13.0 / Prettier 3.9.10。合并配置保留双方静态检查规则。另将 JS 固定 LF，解决 Windows checkout 后的 Prettier 换行报错。没有删除对方业务功能，也没有为本次同步创建提交。

合并后重新运行，均通过：

- [后端 252 项](evidence/c4/develop-sync-backend.txt)。
- [桌宠 301 项](evidence/c4/develop-sync-desktop.txt)，使用 offscreen 和隔离测试凭据。
- [部署 26 项、无跳过](evidence/c4/develop-sync-deployment.txt)，116.19 秒，包含真实 Nginx/HTTP/TLS/WS、启停、备份恢复及历史 schema 回滚；[JUnit](evidence/c4/develop-sync-deployment.xml)。
- [C3 真实后端集成 10 项](evidence/c4/develop-sync-c3-integration.txt)，仅微信上游为 Mock。
- [小程序检查](evidence/c4/develop-sync-frontend.txt)：ESLint、Prettier、WS 逻辑 7 项及 C3 逻辑 13 项，两组入口均执行。
- [Ruff 与文档检查](evidence/c4/develop-sync-static.txt)：160 个 Python 文件格式通过；相对文件链接按该次检查记录，后续说明修改再核对。

[结果摘要](evidence/c4/develop-sync-summary.json)；[最终 pre-commit](evidence/c4/develop-sync-precommit.txt) 的 Ruff、格式、空白和密钥扫描均通过，私有配置仍被忽略。日志采集器追加的末尾空行已移除，完整原始日志保存在本机审计目录。同步仅发生在本机，未替用户更新服务器应用；此前手机人工结果仍对应当时已验证的 C3 客户端与线上服务，不能自动改称“新版本服务器部署通过”。当前已启动合并后的桌宠代码连接原云端，用户确认可见且声音开启后，已完成下述专用电脑提醒核验。正式域名/HTTPS/WSS 与真实图片识别继续按用户要求暂缓。

## 合并后桌宠实际提醒（2026-10-25）

使用合入 develop 9bca38f 的本机 C4 工作树运行桌宠，连接原云端 HTTP/WS。用户确认桌宠可见、声音开启后，创建唯一标记 C4-PC-reminder-de83dace，channel=pc，计划北京时间 12:31:43 到期。用户明确反馈气泡和语音均出现、未观察到重复。

[提醒核验记录](evidence/c4/desktop-reminder.json)显示服务器状态 sent、attempts=1、done=1；核对后按原 ID 和唯一标题删除，读回确认清理。客户端精确展示/语音时间未测量；seconds_after_due 是服务器查询/清理时刻，不能当作展示延迟。线上扫描间隔仍为 30 秒，不能据此宣称 B2 的 5 秒口径通过。仅 PC 通道，没有创建微信订阅提醒。

用户提供只读结果确认线上为 d418655、跟踪工作区干净、MainPID62174/NRestarts0、active/running/enabled，ps 名称筛选中只有 PID62174/PPID1 的 python，见[线上版本和进程](evidence/c4/server-revision-process.json)。它与本机合入的 develop 9bca38f 分开记录；没有自行升级或重启服务器。正式域名、实际识别及另一成员独立复现仍按前述边界保留。没有创建提交或推送。

## 服务器隔离回滚工具

新增 scripts/check_server_rollback.py，复用现有 backup_backend_db.backup_database，只从 Git 对象提取历史源码到新私有目录，以合成库执行真实 schema 1→2→迁移前副本恢复并用旧代码启动。不会读取生产库、修改 systemd、切换仓库分支或启用微信/模型。工作树 backend/app 与指定版本不一致时先退出。

[相关 4 项回归](evidence/c4/server-rollback-tool-tests.txt)通过，19.40 秒；[JUnit](evidence/c4/server-rollback-tool-tests.xml)。这包含既有历史回滚/协议验证、新 CLI 真实恢复及不匹配源码的预检拒绝；前述合并后完整部署 26 项是新增 CLI 前的独立记录，不冒称本次重跑全部 28 项。另在本机以与线上相同的 d418655 实际运行默认 HEAD 路线，[结果通过](evidence/c4/server-rollback-tool-local-check.json)。用户随后上传并以 idp 用户在 ECS 执行同一隔离演练，[服务器结果](evidence/c4/server-rollback-execution.json)为 passed=true：5ff462f/schema1 → 线上当前 d418655/schema2 → 恢复迁移前副本并用旧代码成功读回。备份后测试新增行被排除，升级副本保留；production_database_opened=false、production_service_changed=false。本轮私有目录 /tmp/c4-rollback-drill-gzjia8zo 保留。该结果是实际 ECS 主机的隔离演练，不等于生产发布或数据库切换。

## 当前结论

IP 开发调试路线已验证：公网 HTTP/WS 鉴权和业务、开发者工具与手机 CRUD、页面实时更新、手机断网补齐及恢复后继续实时更新、systemd 重启持久化、实际桌宠气泡/语音、真实数据备份恢复副本，以及 ECS 隔离历史代码/schema 回滚。运行版本分别记录为线上 d418655、本机工作树合入 develop 9bca38f，不能混称同一次新版本服务器发布。详见[本轮人工核验汇总](evidence/c4/manual-verification-20261025.md)。

到期 5 秒内展示已在用户改为 1 秒扫描后完成，5/5 样本通过，计入时钟误差后最慢上界 2.069 秒，见[实测报告](evidence/c4/desktop-latency-20261025.md)。正式 HTTPS/WSS 与正常合法域名校验在初始诊断后按用户最新要求暂缓：ICP备案未过，本轮继续使用公网IP；用户确认A记录8.148.29.9已启用，传播未复核，见[正式路线边界](evidence/c4/formal-route-20261025.md)；真实视觉识别及小程序界面确认导入/修改/删除已通过并读回，见[视觉报告](evidence/c4/vision-recognition-20261025.md)；另一成员独立复现和手机/基础库精确版本登记仍待补齐。因此不将 Issue #12 整项关闭或标为全部验收通过。本次仍未 commit 或 push，合并结果与 C4 文件保留在本机。演练后[公网健康复查](evidence/c4/server-rollback-post-health.json)为 HTTP200/status:ok。

## 云端到期展示时延补验

用户将扫描间隔由 30 秒改为 1 秒并重启服务，PID65574、active/running。本机带 Paint 后记录的真实桌宠连接当前云端，5 次 PC 提醒全部通过，时钟校正后的最大保守上界 2.069 秒，每条只发送/展示一次且已清理。见[时延报告](evidence/c4/desktop-latency-20261025.md)与[原始证据](evidence/c4/desktop-latency-20261025.json)。前文 30 秒和未计时描述是先前轮次的历史状态。本次没有测语音完成时间或正式 HTTPS/WSS，当前仍未 commit/push。

## 视觉识别恢复核验（配置排查历史）

用户通知硅基流动配置已完成后恢复核验。13:34 上传同一无个人信息的合成课表（1,154,843 字节，PNG 元数据填充超过1MiB），[首次恢复请求](evidence/c4/public-image-recognition-configured-20261025.json)仍返回502，约7.96秒；没有请求课程导入，没有业务测试记录待清理。已请求用户在服务器重启加载配置并提供不含密钥的状态诊断，尚未确认新配置是否已加载。此前“示例Key”的诊断是旧轮次结果，不能据此判断当前真实Key的状态。

用户重启后[安全诊断](evidence/c4/server-vision-config-recheck-20261025.json)确认 key_present=true、key_is_example=true，接口主机 api.siliconflow.cn、路径/v1、模型名已填。已请求用户替换服务器 /home/idp/idp/backend/.env 的 LLM_API_KEY 并重启；保持 API_TOKEN 原值。等待配置完成再发模型请求，未重复调用或导入。

## 视觉配置加载后识别通过

用户替换服务器视觉Key并重启后，真实/api/courses/parse-image返回200，17.13秒，合成课表的课程名、星期、起止时间、教室、教师空值和1～16周全部一致。已对该识别结果进行唯一标记的bulk导入、云端读回和清理。原工具周次JSON表示的比较断言已在同一条记录上修正核验，无重复创建、无业务代码更改。见[本轮视觉报告](evidence/c4/vision-recognition-20261025.md)。用户随后在小程序实际识别并确认导入、编辑改名，云端逐字段核对通过；界面删除后按ID和标记核对均不存在。见[人工结果](evidence/c4/manual-vision-import-20261025.json)。当前无测试课程遗留。

## 域名诊断与继续IP验收

用户在图片和时延补验完成后曾要求恢复正式HTTPS/WSS，初始探测发现A无返回、HTTP备案拦截与HTTPS重置。随后用户明确ICP备案尚未通过，要求继续通过IP验证成果，不使用域名访问服务器；并确认A记录8.148.29.9已启用。配置状态是用户反馈，传播未重新探测。见[诊断和当前验收边界](evidence/c4/formal-route-20261025.md)。没有改客户端/服务器或向域名发送凭据。

## IP路线最终只读复查

根据用户最新指示，在视觉Key配置与多次服务重启后复查现用IP入口，健康、REST正确/缺失/错误凭据、真实WS握手及负向拒绝共7/7通过，见[结果](evidence/c4/ip-route-final-readonly-20261025.json)。本次没有业务写入，已有人工测试记录此前均已清理。开发调试路线成果已验证；正式HTTPS/WSS/正常域名校验和独立复现仍按上述边界保留。本轮未commit/push。
