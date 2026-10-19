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
配置、逐条数据、双版本结果与复现命令见 [测试文档](testing.md) §5.2 与 `docs/evidence/b2/`。

## B3 增量环境（2026-10-14）

沿用上述 Windows 硬件与 Python 3.13.0/3.10.22，基线 `ee1a638`（已集成 PR #22）。B3 未新增运行依赖；当前锁文件包括已合入课表导入功能的 python-multipart。微信实验使用 MockTransport、临时 SQLite、固定/可注入时钟；WS 实验使用本机真实网络、单 worker、1 秒扫描。168 项后端测试分别在两个 Python 版本通过，桌面 106 项通过；详细结果见 [测试文档](testing.md) §5.2 与 `docs/evidence/b3/`。GitHub CI 配置覆盖 Linux Python 3.10/3.12 后端及 Python 3.12 桌面，远端执行结果以对应 PR 检查为准。
## B4 增量环境（2026-10-15）

沿用 Windows 硬件、Python 3.13.0/3.10.22 和已有依赖锁文件；起始基线 `42a95ba`，无新增运行依赖。新增 63 项测试，后端总计 172 项；桌面 106 项。真实验收使用 Uvicorn 单 worker、curl、本机随机端口和临时库，上游流量经既有代理；命令、时间口径与结果见 [测试文档](testing.md) §5.2 与 `docs/evidence/b4/`。
