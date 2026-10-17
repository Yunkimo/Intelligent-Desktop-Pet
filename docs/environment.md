# B1 验证环境

- 日期：2026-10-11（Asia/Shanghai）。
- 基线 SHA：`49944767f441b7c625cbbb48bd28bcff1c08c844`。
- 被测功能提交：`12635feeafe6f1204b33f43fd9485a4853841f75`。
- OS：Windows 11 Home China 64-bit，版本 10.0.26200。
- CPU：Intel Core i7-1165G7，8 逻辑处理器；RAM：约 15.73 GiB。
- Python：3.13.0；兼容回归使用 uv 提供的独立 CPython 3.10.22。
- 运行依赖：见 `backend/requirements.txt`；pytest 9.1.1、Ruff 0.17.0、pre-commit 4.6.2。
- 数据：每个自动化用例独立临时 SQLite；真实网络脚本每次创建 30 条日程。
- 网络：本机 IPv4 loopback，随机空闲端口；无真实客户端设备与公网代理参与收包路径。
- Uvicorn：1 worker，`websockets-sansio`，消息最大 4096 字节；凭证随机生成，不持久化。
- 超时：单连接发送 2 秒、关闭 1 秒；故障注入用例采用更短受控超时。
- 时间：事件信封 UTC；测试不测跨机器时钟误差，也不声称达到提醒端到端延迟指标。
- 依赖下载与 GitHub 访问使用本机现有代理；未更改 Git 全局代理设置。
- 当前不是另一名成员的干净部署复现；该验收仍待执行。

## B2 增量环境（2026-10-12）

硬件、Windows、Python 双版本及后端依赖沿用以上环境。
基线 `9f4e9df7bbc51800be350a06e1084a2e656e6ed6`；被测功能提交
`cbd0f634965abdcd95f4a53896ccee52f6f43aa6`。
每组真实网络测试独立临时库、30 条提醒、1 个 WS 客户端、单 worker；分别使用 1 秒和默认 30 秒扫描。
服务与收包脚本在同一机器，记录 UTC 时间及墙钟漂移估计；不将其作为跨设备时钟同步证明。
配置、逐条数据、双版本结果与复现命令见 [B2 报告](b2-test-report.md)。

## B3 增量环境（2026-10-14）

沿用上述 Windows 硬件与 Python 3.13.0/3.10.22，基线 `ee1a638`（已集成 PR #22）。B3 未新增运行依赖；当前锁文件包括已合入课表导入功能的 python-multipart。微信实验使用 MockTransport、临时 SQLite、固定/可注入时钟；WS 实验使用本机真实网络、单 worker、1 秒扫描。168 项后端测试分别在两个 Python 版本通过，桌面 106 项通过；详细结果见 [B3 报告](b3-test-report.md)。GitHub CI 配置覆盖 Linux Python 3.10/3.12 后端及 Python 3.12 桌面，远端执行结果以对应 PR 检查为准。
## B4 增量环境（2026-10-15）

沿用 Windows 硬件、Python 3.13.0/3.10.22 和已有依赖锁文件；起始基线 `42a95ba`，无新增运行依赖。新增 63 项测试，后端总计 172 项；桌面 106 项。真实验收使用 Uvicorn 单 worker、curl、本机随机端口和临时库，上游流量经既有代理；命令、时间口径与结果见 [B4 报告](b4-test-report.md)。

## C 增量环境（2026-10-12 ~ 2026-10-17）

- 仓库与分支：`Yunkimo/Intelligent-Desktop-Pet`（原名 IDP，2026-10-14 改名）；C3 分支 `feat/miniprogram-c3`、C4 分支 `feat/miniprogram-c4`（均自 develop 切出）。
- 微信开发者工具：Stable 2.01.2510290（Windows）；模拟器 iPhone 12/13 机型；真机预览为本人手机（型号与微信版本待补录）。
- JS 检查环境：本机 Node 24.20.0 / npm 11.19.0（CI Node 22）；eslint 10.12.0 + prettier 3.9.10 精确锁定（miniprogram/package-lock.json）。
- 后端：沿用 B 环境（本机 Python 3.13.2 venv；CI 3.10/3.12）；视觉识别联调用硅基流动 `Qwen/Qwen3-VL-32B-Instruct`（用户实名认证账户）。
- 真机网络：手机与电脑同一 WiFi，电脑局域网 IP 192.168.5.19，防火墙放行 TCP 8001；测试数据均清理。
- C2 验收：模拟器 + 真机各一次「后端加数据 → 页面约 1 秒刷新」人工确认；适配层逻辑验收 7 项入 CI。
- C3 逻辑验收：subscribe 纯函数 + 流程集成 7 项（同意/拒绝/取消/登记重试幂等），本地 Node 实测通过。
- C4 验收：run-backend.ps1 实测启动、check_deployment 5/5、reset_demo 实测（含备份命名修复）。
- 未执行项：微信订阅真机链路（待 B3 合并与模板配置）、他人干净环境部署复现（C-T06）、公网/学生机路线（C-T07）。
