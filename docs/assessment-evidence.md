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

## A6 增量证据（Issue #32，2026-10-19）

系统托盘与开机自启由分支 `feat/a6-system-tray` 交付（提交 `a386313` 注册表管理、`ec8805f` 托盘与隐藏，文档随本提交更新）。

- 托盘：`pet/tray.py` 用当前形象生成 16–64 px 多档图标；左键单击显隐桌宠；右键菜单复用 A5 `Command` 表（`_build_commands(include_hide_to_tray=False)`），追加勾选式「开机自启动」。**2026-10-24 调整：菜单里的「退出」移到最下方**——`_build_commands` 增加 `include_quit` 开关，托盘以 `include_quit=False` 取表后先追加自启、再追加窗口提供的 `_quit_command()`，桌面菜单默认仍以「退出」结尾；新增/更新 `test_tray.py` 的顺序断言与 `test_window_status_badge.py` 的剔除断言。
- 隐藏：桌宠右键菜单顶部新增「隐藏至托盘」。气泡与角标是独立顶层浮窗，实测不会随父窗口隐藏，因此 A6 交付时 `hide_to_tray()` 显式隐藏气泡、Claude 角标与 Codex 角标，恢复时还原隐藏前的显隐状态。**该角标行为已于 2026-10-23 被「角标独立显隐」取代（见下文同名增量证据）：隐藏桌宠后角标按自身开关继续显示。**
- 退出：A5 的「退出」由 `self.close` 改为 `_quit`，置 `_quitting` 后走原有收尾路径；托盘启用时普通关闭只隐藏，托盘「退出」在窗口隐藏状态下也能正常结束进程。
- 开机自启：`pet/autostart.py` 读写 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 的 `IntelligentDeskPet` 值，指向带引号的 `启动桌宠.bat`；注册表是唯一事实源，因此未在 `config.json` 增加 `autostart_enabled` 字段（与 Issue 原范围的有意差异）。非 Windows 返回 False。
- 验证：ruff check/format 通过；合并 develop 的 Codex 双角标后 pytest 182 条通过；真实窗口确认系统托盘可用、图标非空（15×16 至 60×64 五档）、托盘菜单顺序正确、隐藏/恢复气泡角标、真实注册表 enable→is_enabled→disable 往返成功、隐藏状态下退出返回码 0。失败与修正过程见 [测试文档](testing.md) §5.3。上述「隐藏/恢复气泡角标」记录的是 A6 交付时行为，角标部分自 2026-10-23 起改由独立开关控制。

## A9 增量证据（Issue #46，2026-10-19）

Claude Code 状态监控由 PR #49 合并，启动定位、退出残留与气泡遮挡修复由 PR #51 合并。2026-10-19 修复启动时控制台的两行 `Could not parse stylesheet of object StatusBadge`：

- 根因：`StatusBadge` 的 QSS 由三段拼接，前两段是 f-string（`{{`/`}}` 会转义），最后一段是普通字符串，`}}` 原样输出，导致样式表多一个右花括号、Qt 解析失败。
- 修正：提交 `2f00cbd`（`fix(pet): 修复状态角标样式表解析警告`）将末尾改为单个 `}`；新增捕获 Qt 消息的回归测试，修正前失败、修正后通过。
- 验证：ruff check/format 通过；桌宠端 147 条用例通过；真实 `main.py` 运行 8 秒，控制台 0 条解析警告（旧样式表对照为 2 条）。
- 修复提交与文档（`2f00cbd`、`903e97d`）已快进推送至 develop（2026-10-19，CI run 39237613619 全绿）；AI 纠错过程见 [测试文档](testing.md) §5.3。

## 角标独立显隐增量证据（2026-10-23）

分支 `feat/badge-independent-visibility`，提交 `2760f72`。

- 行为：`hide_to_tray()` 只隐藏桌宠与气泡，不再连带隐藏 Claude / Codex 角标；新增右键与托盘共用的「显示状态角标」勾选项，写入 `config.json` 的 `status_badges_visible`。
- 实现：`StatusBadge.set_user_visible()` 与状态驱动的 `set_state()` 取交集决定显隐；关闭期间状态继续更新，重开时按当前状态恢复。沿用 `_build_commands()` 命令表，托盘菜单自动复用新命令。
- 测试：新增 `test_badge_visibility.py`（开关持久化与双向切换）、`test_status_badge.py::test_user_visible_switch_keeps_state` 与 `test_config.py` 三项（默认值隔离、持久化往返、更新保存）；另补启动时恢复隐藏状态与菜单未勾选态断言。原 A6 托盘回归用例改为断言角标不随桌宠隐藏。桌宠端 208 条用例、ruff check/format 通过；测试补强与文档修正见 PR #55 追加提交。
- 待办：真实窗口人工验收（隐藏桌宠后角标保留、勾选开关即时生效）。Issue #54 / PR #55 已于 2026-10-23 创建并分配成员 A，待人工验收后合并。

## 角标自由移动增量证据（Issue #56，2026-10-23）

Claude/Codex 状态角标由分支 `feat/badge-draggable` 交付（PR #57），在既有自动摆位之上增加「手动拖拽 + 双击复位」：

- 可交互：移除角标的 `WA_TransparentForMouseEvents`，按下左键拖动超过 4px 阈值即移动并标记手动位置；`_position_status_badge()` 跳过手动角标，其余角标仍正常跟随桌宠自动摆位。
- 复位：双击角标清空手动标记并发 `position_reset` 信号，窗口重新执行自动摆位。
- 边界：角标位置夹在屏幕可用区域内，避免拖出屏幕后无法再双击复位；手动位置仅本次运行有效，不持久化（与会话性定位一致）。
- 验证：ruff check/format 通过；桌宠端 pytest 213 项全过（合并 #55 的 208 项后 + 新增 5 项拖拽/复位用例）。未改变既有自动摆位规则，仅在其上叠加手动覆盖，不涉及后端与小程序。

## Token 用量查看增量证据（2026-10-24）

分支 `feat/token-usage`，把 LLM 消耗从「完全不可见」变成可自查的三块信息。

- 采集：`pet/providers.py` 新增可选 `on_usage` 回调，流式在最后一个 chunk 上采集（实测 DeepSeek 的 usage 帧 `choices` 长度为 1、`delta` 为空，标准 OpenAI 则在 `choices=[]` 的独立帧上，两种都在判断 `choices` 之前读取）；非流式读 `resp.usage`。上报异常一律吞掉，旁路统计不影响对话；`chat_with_tools` 返回结构保持 `{content, tool_calls}` 不变。服务商不认 `stream_options` 时，仅在尚未收到任何帧时降级重试一次并记住，避免重复计费。
- 记账：`pet/usage.py` 的 `UsageStore` 把 usage 归一为 prompt/completion/cached（优先 `prompt_cache_hit_tokens`，回退 `prompt_tokens_details.cached_tokens`），按北京时间分天聚合写入 `data/usage.json`；线程锁 + 临时文件 `os.replace` 原子写，坏 JSON 归零重建，按天明细按 `usage_retention_days` 裁剪而总计不裁剪，金额用 `Decimal` 存字符串。
- 费用：`pet/pricing.py` 内置 DeepSeek 价目（2026-10-24 抓取，只存高峰价、空闲价乘 0.5），`deepseek-chat` 等旧名按别名归一到现役模型；高峰按北京时间工作日 9–12、14–18 判定，法定节假日未建模、会高估，界面与手册均写明。
- 余额：`pet/balance.py` 只对接官方余额接口（DeepSeek `GET /user/balance`、Moonshot `/v1/users/me/balance`），base_url 归一后忽略 path，禁止跟随重定向以免 `Authorization` 被带到其他 host，401/超时/坏 JSON 各给可读文案且不含 key；`BalanceTarget.api_key` 用 `repr=False`。
- 入口：`pet/rice_button.py` 的米饭图标是桌宠窗口的子控件，随窗口移动不可分离；图标设 `WA_TransparentForMouseEvents`，点击与拖拽统一由 `PetWindow` 的命中测试分流（点图标开窗口、点头像唤输入框、从图标按下仍可拖动桌宠），悬停时切换手型光标；素材缺失降级为文字块。
- 线程：`BalanceWorker(QThread)` 的 parent 是桌宠窗口而非对话框，对话框持注册表并在 `finished` 时 `deleteLater`；关闭窗口只 `request_stop` 不阻塞，应用退出时 `shutdown()` 有限等待 1.5 秒。
- 跳转 API 网站：余额区「刷新余额」下方新增「跳转至API网站」，用 `QDesktopServices.openUrl` 在系统默认浏览器打开；目标优先取 `config.json` 的 `api_website`；未配置时由 `pet/balance.py::console_url` 按服务商给控制台用量页（DeepSeek → `https://platform.deepseek.com/usage`），未收录的服务商退回接口站点根（`website_url` 只保留 scheme+host）；地址为空时按钮置灰并给出提示，改完「API 地址」即时刷新提示。
- 余额详情：账户余额改为分行字段（服务商 / 币种 / 总余额 / 赠送·充值 / 状态 / 查询时间），失败时保留上次数值只更新状态行；因 DeepSeek、Moonshot 均未开放历史用量接口，界面常驻一行说明「账户侧近七天用量无法获取」，不拿本地数字冒充账户用量。
- 新用户入口：用量窗口下方提供「配置 API」三栏——API Key（`LLM_API_KEY`，桌宠接入用）、API 地址（`LLM_BASE_URL`，可留空）、账户查询 Key（`ACCOUNT_API_KEY`，可留空回退）。`pet/config.py::save_env_values` 按行合并 `.env`（保留注释与既有键、同名原地替换、缺失追加），保存后立即更新内存配置：改了推理 key/地址发 `llm_config_changed` 信号，窗口据此重建 `LLMClient`；账户 key 留空时沿用推理 key。输入框密码模式、保存后清空、只回显头尾，界面与截图不留明文；`config.json` 会被提交，密钥一律不进该文件。
- 验证：ruff check/format 全过；桌宠端 pytest 301 项全过（213 + 新增 88 项：价目边界、归一化、聚合/裁剪/并发、余额解析与错误映射、图标几何与点击分流、对话框汇总与线程收敛、`.env` 写入与窗口内接入配置、余额详情字段化、UTC 时区分桶、跳转 API 网站）。真实链路实测：真实 API 一次流式 + 一次工具调用后 `data/usage.json` 记录 2 条、费用非 0、重新加载一致；真实余额接口返回 200 并在窗口分行填出服务商 DeepSeek、币种 CNY、总余额、赠送/充值、状态「可用」与查询时间，该接口在测试网络下约 8 秒返回。

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
