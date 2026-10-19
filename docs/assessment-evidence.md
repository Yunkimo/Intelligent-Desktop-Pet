# 考核证据索引

## A1–A4 桌宠端

关联 issue [#1](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/1)、[#2](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/2)、[#3](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/3)、[#4](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/4)，PR [#17](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/17)。以下是桌宠端 A1–A4 的证据，不代表项目已完成全部考核。

关键提交（`feat/desktop-agent`，已合入 `develop`）：

- A1 BackendClient：`3385fe5`；本地代理修复 `7905385`（httpx `trust_env=False`）
- A2 工具调用：`67de45f`；DeepSeek 422 修复 `94861b7`（tool_calls 回传补 `type`）
- A3 健康关怀：`c273278` → `d5dd38e` / `a0c83e2` / `9ff1bef`；配置默认 45 分钟 `1d7f06e`
- A4 实时接收：`fbae3c3`

| 项目 | 当前证据与状态 |
|---|---|
| 1 编码规范、6 提交格式、7 职责与粒度、8 提交检查 | CONTRIBUTING + Ruff + pre-commit；`ruff check pet/ tests/` 全过；Conventional Commits（`feat/fix/refactor/chore(pet): 中文`），一任务/一修复一提交 |
| 2 Git 协作、20 分工、21 测试设计贡献 | `feat/desktop-agent` 分支 + issue #1–#4 + PR #17；A1–A4 单测注入假时钟/假空闲源（`tests/test_health.py` 等），共 56 用例；他人评审待 B/C |
| 3 忽略规则 | `.gitignore` 排除 `.env`、`data/`、`__pycache__/`、构建产物；`agent.md` 走 `.git/info/exclude` 不入库 |
| 4 依赖与许可证 | `requirements.txt`（httpx/openai/websocket-client/PyQt6 等）+ `THIRD_PARTY_NOTICES.md`；形象素材为自备图片（PNG/WebP），素材授权待核验 |
| 5 配置、9 分层与数据源、16 安全 | `.env`（LLM_API_KEY/BACKEND_URL/API_TOKEN）与 `config.json`（非敏感）双源解耦；密钥不入库不入截图；后端唯一数据源，桌宠经 `BackendClient`（`trust_env=False` 防代理劫持）+ `WsListener` 访问 |
| 10 可运行脚本、13 实测、14 环境、15 用例 | `setup.bat`/`启动桌宠.bat`/`main.py`；2026-10-17 复跑：A1 health 200、A2 真实天气摘要 + 日程落库（LLM 工具循环 2 次调用）、A4 真实 WS 收到 `task.created`；A3 为 6 例单测（手动气泡验收经决定跳过）；`docs/environment.md`；116 单测全过。原始记录见 `docs/evidence/a-desktop/` |
| 11 帮助与手册 | `docs/user-manual.md`（安装/运行/自定义）；A1–A4 联调说明待补 |
| 12 重构量化 | A0 桌面模块采用策略+工厂（ChatProvider/形象引擎）、命令模式与纯函数抽取；前后行数、提交号与边界声明见 [重构效果量化分析](refactor-report.md) |
| 17 演示视频 | 未录制（需本人录制，仅能提供脚本/指引） |
| 18 工作量、19 绩效 | `docs/workload.md` 台账；A 条目待登记，点数与绩效比例待团队确认 |

未闭环项：A4 `reminder.due` 端到端依赖 B2 到期调度器（issue #6）；A3 手动 GUI 气泡经决定跳过（逻辑以 6 例单测覆盖）。不以单测/Mock 替代真实端到端验收。

## A9 增量证据（Issue #46，2026-10-19）

Claude Code 状态监控由 PR #49 合并，启动定位、退出残留与气泡遮挡修复由 PR #51 合并。2026-10-19 修复启动时控制台的两行 `Could not parse stylesheet of object StatusBadge`：

- 根因：`StatusBadge` 的 QSS 由三段拼接，前两段是 f-string（`{{`/`}}` 会转义），最后一段是普通字符串，`}}` 原样输出，导致样式表多一个右花括号、Qt 解析失败。
- 修正：提交 `2f00cbd`（`fix(pet): 修复状态角标样式表解析警告`）将末尾改为单个 `}`；新增捕获 Qt 消息的回归测试，修正前失败、修正后通过。
- 验证：ruff check/format 通过；桌宠端 147 条用例通过；真实 `main.py` 运行 8 秒，控制台 0 条解析警告（旧样式表对照为 2 条）。
- 分支 `fix/status-badge-stylesheet` 已推送，PR 待用户确认；AI 纠错过程见 [测试文档](testing.md) §5.3。

## B1 后端

关联 [#5](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/5)，PR [#16](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/16)。以下是本议题的证据，不代表项目已完成全部考核。

| 项目 | 当前证据与状态 |
|---|---|
| 1 编码规范、6 提交格式、7 职责与粒度、8 提交检查 | CONTRIBUTING、Ruff、pre-commit；检查结果见测试报告 |
| 2 Git 协作、20 分工、21 测试设计贡献 | 功能分支与本次提交；他人评审尚未完成 |
| 3 忽略规则 | 继承 develop 忽略规则；测试使用临时数据库，守则在仓库外 |
| 4 依赖与许可证 | 后端锁文件与 THIRD_PARTY_NOTICES；全项目素材授权需各成员继续核验 |
| 5 配置、9 分层与数据源、16 安全 | `.env.example`、广播服务、WS 路由、接口契约及鉴权/脱敏测试 |
| 10 可运行脚本、13 实测、14 环境、15 用例 | `scripts/smoke_backend_ws.py`、测试报告及原始结果 |
| 11 帮助与手册 | 用户手册新增 B1 联调说明 |
| 12 重构量化 | 本次为新增功能；项目整体重构收益见 [重构效果量化分析](refactor-report.md)，不重复申报 |
| 17 演示视频 | 未录制 |
| 18 工作量、19 绩效 | workload 台账；实际验收与分配待确认 |

提醒延迟测量、微信真机接收、部署复现、跨端联调与项目完整视频
尚未执行，不以 B1 网络广播脚本替代这些验收。

## B2 增量证据（Issue #6）

历史 B1 状态保留；2026-10-12 已补充后端提醒延迟测试，尚无 GUI 展示和微信验收。

| 对照项目 | B2 证据与限制 |
|---|---|
| 1、6、7、8 | 英文功能提交 cbd0f63；格式/静态/空白/密钥检查见 [测试文档](testing.md) §5.3 |
| 2、20、21 | 关联既有 #6，功能分支交付；人工评审待执行，不把 AI 自查当作成员评审 |
| 3、4、16 | 临时测试库、守则仍在仓库外；未新增依赖；双版本审计、诊断鉴权和异常脱敏用例 |
| 5、9 | 集中调度配置、UTC 时间、持久状态与单 worker 约束，见 [契约](api-contract.md) |
| 10、11、14 | 迁移/备份/恢复脚本 `scripts/backup_backend_db.py`、用户手册、[环境增量](environment.md) |
| 12 | 新增功能；无独立重构基线，项目整体收益见 [重构效果量化分析](refactor-report.md) |
| 13、15 | 63 项自动化、覆盖率约 96%、三组各 30 条真实网络数据，见 [测试文档](testing.md) §5.2 与 `docs/evidence/b2/` |
| 17 | 系统演示视频未录制 |
| 18、19 | [台账](workload.md) B2 初估 8 点，实际验收点数、工时与绩效仍待确认 |

AI 纠错过程见 [测试文档](testing.md) §5.3。跨端时间与完成语义为待评审提案，
没有宣称任务全部验收、三端联调完成或生产部署恢复完成。

### 2026-10-12 用户要求的 B2/A4 验收补充

新增真实气泡截图、复现脚本及验收结论（`docs/evidence/b2/`）。普通到期链路通过，
但原 60 秒条件与默认轮询不兼容、A4 同事件重复展示仍未解决；完整验收未通过。
这补充了前述“GUI 未验”的历史记录，不代表语音、微信或其他成员评审通过。

### B2 / A4 修复后

用户授权统一修复后，`docs/evidence/b2/final-visible-gui-30.json` 记录 30/30 真实气泡限时显示、
故障重连去重及真实播放器完成播放；桌宠 106 项自动化通过。
前述失败历史继续保留，未改写为成功；窗口重启去重、微信、独立人工评审仍不在本轮结论中。

## B3 增量证据（Issue #7，2026-10-14）

| 评分项 | 本次证据与边界 |
|---|---|
| 1、6、7、8 规范与提交 | CONTRIBUTING、Ruff、pre-commit；功能与文档分开提交，英文 Conventional Commits |
| 2、20、21 Git 与协作 | 既有 Issue #7、feat/backend-realtime 分支及关联 PR；设计、测试、文档均有版本差异，其他成员评审待完成 |
| 3、4 忽略与供应链 | 临时测试库、已有 .gitignore、MIT 与第三方说明；本地守则在仓库外；无新增运行依赖，后端审计未发现已知漏洞 |
| 5、9、16 配置、解耦、安全 | 环境变量、HTTP 适配器、会话摘要、归属校验与脱敏，见 [API 契约](api-contract.md) §B3 与 [信息安全设计](security.md) §7 |
| 10、11 可运行与帮助 | Mock 演示脚本、用户手册、配置与单 worker 启动命令 |
| 12、13、14、15 重构、量化、环境、测试 | [测试文档](testing.md) §5.2：168 项后端、106 项桌面；30 次发送/1 次 token、0 次重复；渠道隔离回归。重构收益统一见 [重构效果量化分析](refactor-report.md)，不虚构改前性能 |
| 17 视频 | 尚待 C3 真机联调后录制，Mock 数据不替代视频 |
| 18、19 工作量与绩效 | [台账](workload.md)：B3 初估 8 点；实际验收和分配比例待团队确认 |

本次体现 Python 异步、事务、异常分类、适配器及依赖注入，CI 自动运行后端 Mock 冒烟。服务器部署复现、嵌入式设备验证不在本轮证据内；AI 使用和真实纠错见 [测试文档](testing.md) §5.3。
## B4 增量证据（Issue #8，2026-10-15）

| 评分项 | 证据及限制 |
|---|---|
| 1、6、7、8 规范与提交 | Ruff、pre-commit、英文 Conventional Commits，功能/测试、共享测试维护、文档按职责提交 |
| 2、20、21 Git 协作与分工 | 独立 feat/backend-web-query 分支关联既有 #8；A/C 接入及独立评审待确认 |
| 3、4 忽略与供应链 | 临时数据库、仓库外 agent 守则、现有忽略规则；无新增运行依赖，依赖审计无已知漏洞 |
| 5、9、16 配置、解耦、安全 | 路由与网络适配器分层，配置化资源预算、固定上游、超时/大小限制，见 [API 契约](api-contract.md) §B4 与 [信息安全设计](security.md) §8 |
| 10、11 脚本与帮助 | 真实 Uvicorn + curl 脚本、用户手册和部署命令；Mock 与 live 分开 |
| 12、13、14、15 设计增益、量化、环境、测试 | [测试文档](testing.md) §5.2：172 项后端、106 项桌面；真实两种摘要、失败记录、压缩修正。重构收益统一见 [重构效果量化分析](refactor-report.md)，未虚构改前性能 |
| 17 视频 | 尚未录制，不把 curl JSON 当作系统视频 |
| 18、19 工作量与绩效 | [台账](workload.md) 初估 5 点，实际验收和分配待团队确认 |

本次体现 Python 异步、流读取、有限解压、HTML 解析、适配器和依赖注入。公网服务器复现、嵌入式验证及 GUI 联调不在已完成证据内；AI 真实纠错见 [测试文档](testing.md) §5.3。

## 原始证据归档（`docs/evidence/`）

| 范围 | 目录 | 内容 | 状态 |
|---|---|---|---|
| A1–A4 桌宠端 | `evidence/a-desktop/`、`evidence/b2/` | 116 项 pytest 与行覆盖率；A1–A4 端到端 JSON/日志（health、天气、日程、LLM 工具循环、真实 WS 事件）；30 条真实气泡、截图、语音播放日志、故障重连数据 | 完整 |
| B1–B4 后端 | `evidence/b1/`–`evidence/b4/`、`evidence/current/` | pytest 输出、覆盖率、真实网络逐条数据、依赖审计、压缩边界矩阵 | 完整 |
| C1–C5 小程序 | 无 | — | C3/C4 真机联调与部署验收完成后由 C 补录，当前不臆造 |

各轮结论汇总在 [测试文档](testing.md) §5；目录内文件为执行时原始输出，不事后修改。
