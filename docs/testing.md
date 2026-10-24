# 测试文档

## 1. 测试策略

按「纯逻辑 → 无界面 UI → mock 隔离外部依赖」分层：

- **纯逻辑单测**：配置、记忆、人设、气泡折行与摆位、命令、时间规整、图片缩放等无副作用逻辑，直接断言。
- **无界面 Qt 测试**：通过 `QT_QPA_PLATFORM=offscreen` 在无显示环境跑 Qt 组件；CI 另用 `xvfb-run` 提供虚拟 X 显示器，供 `pynput` 探测 X 连接。
- **mock 隔离网络**：LLM 提供者用假客户端替换，验证流式拼接、回调与异常包装，不真正联网；后端视觉解析、微信与天气/搜索上游分别用假 HTTP 响应替换，覆盖超时、上游报错等分支。
- **接口级测试**：后端用 FastAPI `TestClient` 走真实路由 + 临时 SQLite，覆盖鉴权、CRUD、WebSocket 广播、调度器与适配器。

真实网络与硬件由脚本和人工验证覆盖，不进入自动化单测：

| 脚本 | 覆盖 |
|---|---|
| `scripts/smoke_test.py` | 桌宠端真实 LLM/TTS 与麦克风、whisper 模型 |
| `scripts/smoke_backend_ws.py` | 真实 Uvicorn + WebSocket 广播与握手鉴权 |
| `scripts/smoke_backend_scheduler.py` | 真实网络下的提醒到期延迟与重复抑制 |
| `scripts/smoke_backend_wechat.py` | 微信发送链路的 Mock 上游演示（无需真实凭证） |
| `scripts/smoke_backend_web_query.py` | 天气/搜索（默认 Mock，`--live` 走真实上游） |
| `scripts/check_backend_compression.py` | gzip/deflate 压缩边界矩阵（离线） |
| `scripts/acceptance_reminder_gui.py` | 真实桌宠气泡展示、故障重连与语音播放验收 |

## 2. 运行方式

```bash
pip install -r requirements-dev.txt

# 桌宠端（仓库根目录）
ruff check main.py pet tests
pytest tests/ --cov=pet --cov-report=term-missing

# 后端（backend/ 目录）
cd backend
ruff check . ../scripts
pytest --cov=app --cov-report=term
```

CI（GitHub Actions）在 main/develop 的 push 和 PR 时执行上述步骤，并额外运行后端 WebSocket、调度器、微信 Mock 与天气/搜索 Mock 冒烟脚本、压缩边界脚本、`detect-secrets` 密钥扫描与 `pip-audit` 依赖漏洞审计。桌面人工冒烟与 GUI 验收脚本不在 CI 中运行。

## 3. 测试用例清单（当前仓库口径）

### 3.1 桌宠端（`tests/`，116 个用例，2026-10-17 快照）

| 文件 | 覆盖点 | 用例数 |
|---|---|---:|
| `test_agent.py` | 工具循环次数上限、最终流式回复、未知工具回传 | 3 |
| `test_backend_client.py` | REST 封装、鉴权头、绕过系统代理、非 JSON 2xx、CRUD、ws URL/事件解析 | 9 |
| `test_bubble.py` | 折行纯函数（空/超长/换行）、气泡流式追加、气泡摆位翻转/夹紧/上方覆盖 | 8 |
| `test_commands.py` | 命令默认值与触发、菜单展开顺序、子菜单嵌套与生命周期、可勾选初始态、禁用命令 | 8 |
| `test_config.py` | 配置默认值、环境变量覆盖、config.json 字段、健康项、LLM 生成参数、更新/人设方法、旧音色迁移 | 7 |
| `test_event_dedup.py` | 实时事件去重（重复抑制、重新安排、失败可重试、过期淘汰、容量上限） | 15 |
| `test_health.py` | 久坐阈值、离座清零、周期重复、在座判定 | 6 |
| `test_hotkey.py` | 全局快捷键注册、组合键解析与触发 | 8 |
| `test_image_utils.py` | 图片缩放/裁剪纯函数 | 5 |
| `test_memory.py` | 增删顺序、轮数裁剪、持久化往返 | 4 |
| `test_persona.py` | 人设提示词包含名字/性格/语气 | 1 |
| `test_providers.py` | 流式拼接与回调、异常包装、tool_calls 回传（空/单/多条）、生成参数、工厂、LLM 门面 | 10 |
| `test_timeparse.py` | 「今天/明天/后天 + 时刻」→ ISO、ISO/未知输入透传 | 6 |
| `test_tools.py` | 工具注册表 schema、格式化缺字段、创建/更新/删除、联网失败、自然时间规整 | 14 |
| `test_tts.py` | TTS 文本切分、音色参数、离线回退 | 6 |
| `test_ws_listener.py` | WebSocket 消息解析、重连、事件分发 | 6 |

合计 **116 个用例**（pytest 收集口径，含参数化展开），为 2026-10-17 的清单快照，全部通过。

> 该表之后新增了 `test_tray.py`、`test_status_badge.py`、`test_monitor_toggle.py`、`test_badge_visibility.py` 等文件；当前 develop 共 201 项、本分支 208 项。最新清单与数量以 `pytest --collect-only` 为准，不在本表逐行回填。

### 3.2 后端（`backend/tests/`，243 个用例）

| 文件 | 覆盖点 | 用例数 |
|---|---|---:|
| `test_api.py` | 健康检查公开、缺/错 token 拒绝、课表/任务/提醒 CRUD 与部分更新 | 6 |
| `test_course_import.py` | 图片识别导入鉴权、未配置 503、成功解析、无课表 422、上游错误 502、超时 504、文件过大 413、批量落库（合法入库/非法跳过/回滚） | 14 |
| `test_db_migrations.py` | 建库、字段迁移、重复初始化幂等 | 4 |
| `test_logging_config.py` | Uvicorn 彩色/普通日志插值、访问日志字段保留、查询参数脱敏回归 | 12 |
| `test_scheduler.py` | 到期边界、扫描与并发领取、发送失败/超时/取消、租约恢复、迁移备份、时区与非法输入 | 33 |
| `test_vision.py` | 视觉模型响应解析、节次/周数映射、备注防臆造、异常降级 | 28 |
| `test_web_query.py` | 天气/搜索鉴权、输入校验、上游状态映射、超时与大小预算、压缩、链接安全、日志脱敏 | 63 |
| `test_wechat.py` | 登录会话、授权归属、token 缓存/刷新、幂等发送、故障恢复、迁移及渠道隔离 | 59 |
| `test_ws.py` | WebSocket 鉴权、广播推送、断线清理、事件格式 | 24 |

合计 **243 个用例**（pytest 收集口径），本地 pytest 全部通过、行覆盖 95%（原始输出见 `docs/evidence/current/`）；CI 在 Linux Python 3.10/3.12 的后端矩阵与 Python 3.12 桌面环境执行。

> 口径说明：文档中的「用例数」按 pytest 收集（参数化展开）计；按 `def test_` 计为 230 个（桌面 105 + 后端 125），两者不是同一口径，不混用。

### 3.3 B1 WebSocket 用例组设计

| 用例组 | 前置与操作 | 预期 |
|---|---|---|
| B-T01 | 临时库、测试 token；执行既有六例 | 健康检查、REST 鉴权和 CRUD 不回退 |
| B-T02 鉴权 | 缺失、空、错误、重复 token；另测服务未配置 | 拒绝且不注册；普通 HTTP GET 不是 WS 成功 |
| B-T02 广播 | 两客户端连接，POST 日程/课表 | 同一 event_id、UTC 时间、正确资源 ID，REST 可查已提交状态 |
| B-T02 隔离 | 可控慢连接、发送异常、并发广播 | 正常连接先收包；异常连接被移除，同一连接不并发写 |
| B-T04 清理 | 重复注册、断线、取消、关闭时握手 | 无重复登记、无残留连接；关闭有时间上限 |
| B-T04 一致性 | 数据库写入异常、推送异常 | 前者不通知；后者仍保留成功的 REST 写入 |
| B-T06 | 伪造客户端消息、无效 schema、query 日志 | 拒绝客户端发布；无效事件不发送；日志不留 query |
| 网络脚本 | 独立 Uvicorn 进程、临时数据库、两个客户端 | 真实 HTTP Upgrade、30 次收包一致、两类握手拒绝、日志脱敏 |

慢连接等网络故障通过可控假传输测试，与真实网络脚本分开报告。网络脚本退出会终止测试进程，不用该步骤证明生产服务器优雅停机；应用生命周期与关闭边界由自动化测试验证。

## 4. 实验环境

依据 `docs/environment.md`（B1 基线）与 B2–B4 轮次记录：

| 项 | 值 |
|---|---|
| OS | Windows 11 Home China 64-bit 10.0.26200（开发）/ Ubuntu latest（CI） |
| 硬件 | Intel Core i7-1165G7，8 逻辑处理器；RAM 约 15.73 GiB |
| Python | B2–B4 轮次为 3.13.0 与独立 CPython 3.10.22（兼容回归）；当前开发虚拟环境为 3.14.5 / CI 后端 3.10 与 3.12、桌面 3.12 |
| 关键依赖 | PyQt6 6.11、openai 3.31、edge-tts 7.3、faster-whisper 1.2、pytest 9.1、Ruff 0.17、pre-commit 4.6 |
| 测试框架 | pytest 9+、`QT_QPA_PLATFORM=offscreen`（CI 叠加 `xvfb-run`） |
| 数据 | 每个自动化用例独立临时 SQLite；真实网络脚本每轮 30 条数据；不触碰用户数据库 |
| 网络 | 本机 loopback、随机空闲端口、单 Uvicorn worker；真实上游经既有代理，凭证随机生成且不持久化 |

## 5. 结果

### 5.1 覆盖率

最近一次全量行覆盖率测量（后端 `app/`）：

| 轮次 | 语句 / 覆盖 | 覆盖率 | 说明 |
|---|---|---:|---|
| B1（2026-10-11） | 353 / 328 | 93% | WebSocket 路由与推送；变更前基线 6 例，本议题后 30 例 |
| B2（2026-10-12） | 561 / 538 | 95.90% | `scheduler` 100%、`reminder_store` 97% |
| B3（2026-10-14） | 1153 / 1086 | 94.19% | 微信四模块行覆盖 100% |
| B4（2026-10-15） | 1059 / 994 | 93.86% | 路由 100%、适配器 98.54% |
| 当前 develop（2026-10-17） | 1385 / 1315 | 95% | B3+B4 合并后 243 项通过；`wechat_dispatcher`/`wechat_store` 100% |

B3/B4 为并行分支上的独立测量，编号不同源于分支代码范围不同，不能直接相减比较。当前 develop 的原始输出见 `docs/evidence/current/backend-pytest-coverage.txt`。

桌宠端 2026-10-17 测量时为 116 项通过，行覆盖率 56%（`pet/` 1489 语句、829 覆盖；B1 阶段为 50%），原始输出见 `docs/evidence/a-desktop/desktop-pytest-coverage.txt`。此后 A6/A9/A10 继续增加用例，桌宠端现为 develop 201 项、本分支 208 项，覆盖率尚未重新测量。界面层 `window`/`sprite`/`hotkey_dialog` 覆盖较低，原因见 §5.4。

后端高覆盖模块：`scheduler`/`schemas`/`main`/`logging_config`/`reminder_time` 100%、`push_service` 99%、`course_import` 98%、`db` 96%。桌宠端：`tts` 98%、`event_cache` 94%、`backend_client` 93%、`tools` 93%、`memory` 93%、`agent` 91%、`llm`/`providers` 89–97%。

### 5.2 分阶段增量与量化证据

| 轮次 | 后端用例 | 桌面用例 | 关键量化结果 | 原始数据 |
|---|---:|---:|---|---|
| B1（WebSocket 广播） | 109 | 106 | 两客户端各 30 事件、ID 一致；非法握手 403 | `docs/evidence/b1/` |
| B2（提醒调度） | 63（该分支基线 30 + 新增 33） | 106 | 三组真实网络各 30 条：30/30 接收、0 超时/重复；1 秒扫描 p50 749 ms / p95 948 ms；30 秒扫描 p50 14235 ms / p95 27944 ms | `docs/evidence/b2/` |
| B2/A4 修复后 | 63 | 106 | 30/30 真实气泡 5 秒内显示；p50 0.740 s、p95 1.294 s、max 1.518 s；同一 event_id 收到 2 次、气泡/语音各 1 次 | `docs/evidence/b2/` |
| B3（微信 + 实时） | 168 | 106 | 30 次发送只取 1 次 token、重复发送 0；真实 WS 到期 30/30、p95 369 ms；新增 59 项用例 | `docs/evidence/b3/` |
| B4（天气/搜索） | 172 | 106 | 63 项新增用例；真实 curl 天气 2308 ms、搜索 1707 ms；压缩边界 80/80；日志修正后 184 项 | `docs/evidence/b4/` |
| A1–A4 端到端（2026-10-17） | — | 116 | 真实后端 health 200；真实天气摘要 + 日程落库；LLM 工具循环调用 2 个工具、9.5 s；真实 WS 收到 `task.created` | `docs/evidence/a-desktop/` |
| 当前 develop（2026-10-23） | 243 | 201 | 后端为 B3+B4 合并后的 168 + 63 + 12 = 243；桌宠端经 A6/A9 由 106 增至 201（2026-10-17 时点为 116） | 本地 pytest 收集 |
| 角标独立显隐（2026-10-23） | — | 208 | 新增/调整 7 项角标显隐用例（开关切换、持久化往返、启动恢复、菜单勾选态、托盘独立）；隐藏桌宠后角标保持显示 | 本地 pytest 收集 |
| 角标自由移动（2026-10-23） | — | 213 | 合并角标显隐的 208 项后新增 5 项拖拽/复位用例（拖拽移动并标记、双击复位、可接收鼠标、拖出屏夹回、自动摆位跳过手动角标）；ruff check/format 全过 | 本地 pytest 收集 |
| Token 用量查看（2026-10-24） | — | 293 | 新增 75 项：价目时段边界与别名（9）、usage 归一化与聚合/裁剪/并发/容错（15）、余额地址归一与错误映射（14）、图标加载降级（3）、窗口内图标定位/跟随/点击拖拽分流（8）、用量窗口汇总与余额线程收敛（9）、provider 的流式与非流式 usage 采集及降级重试（9）、`.env` 合并写入与窗口内接入配置（8）、余额栏字段化与失败保留旧值（4）、UTC 时区分桶回归（1）；ruff check/format 全过 | 本地 pytest 收集 |

B3 的 token 缓存「少 29 次、96.67%」是相对「每条发送前取一次」的理论计算值，不是旧版本实测；B2 的 30 秒组不满足五秒目标，按实际分布报告，不套用理想阈值。所有真实网络样本均注明为单轮功能实测，不作为重构性能对比或 p95 承诺。

### 5.3 失败与修复记录（未抹平）

- **B1 基线首跑缺依赖**：首次执行基线时依赖安装尚未结束，出现 `ModuleNotFoundError: fastapi`；安装完成后重新运行六例通过。
- **B1 跨版本依赖不兼容**：websockets 17.2 不支持 Python 3.10，改为按 Python 版本锁定依赖。
- **B1 ISO 8601 解析失败**：Python 3.10 首轮 27 passed、2 failed，两例测试无法解析带 `Z` 后缀的时间；修正测试时间解析后通过，并补关闭中握手的并发边界用例，共 30 例。
- **B1 提交检查修复**：`backend/run.py` 格式与用户手册 EOF 多余空行按工具结果修复，未绕过检查。
- **B1 密钥扫描误报**：扫描命中既有文档和桌宠测试中的 `sk-xxxx`、`sk-test`，核实为占位值后仅登记两条文件/内容哈希基线，不排除测试或业务文件。
- **B2 首次验收未通过**：默认 30 秒轮询下「创建后 60 秒内收到」实际为 88.502 秒；A4 未按 `event_id` 去重，同一事件绘制两次气泡。修复后改为 1 秒联调扫描 + 事件 ID LRU 去重，30/30 限时通过；原失败数据保留。
- **B2 并行验收失败**：并行运行三个真实窗口时 30 次通知只记录 26 次绘制；单窗口未确认可见时 29 次绘制。重新在可见桌面下复测后才达到 30/30，说明遮挡会影响视觉验收。
- **B3 CI 密钥扫描误报**：`detect-secrets` 命中测试与 Mock 脚本中的两处假 `WX_SECRET`，仅对这两行加带原因的 `pragma: allowlist secret`，未排除文件或停用扫描。
- **B3 数据库锁竞争**：Python 3.10 下 `test_locked_database_does_not_block_event_loop_and_recovers` 因测试观察者与恢复事务争锁失败；改为通过事件观察真实锁失败，未跳过用例或改动生产逻辑。
- **B4 真实搜索被上游拒绝**：保留两次失败记录；定位到压缩协商差异后补充 gzip/deflate 支持与 5 项压缩用例，最终真实 curl 通过。不将 Mock 结果冒充真实网络验收。
- **B4 终端日志缺陷**：人工验收发现 Uvicorn 进程号显示为 `%d`、访问日志报错；新增 12 项回归（修正前 9 失败 3 通过），修正后 184 项全通过。
- **A6 托盘隐藏未连带浮窗**：初版假设气泡与角标作为顶层子窗会随桌宠窗口一起隐藏，离屏用例实测二者仍可见。改为 `hide_to_tray()` 显式隐藏气泡、Claude 角标与 Codex 角标，恢复时按隐藏前状态还原，并用回归用例锁定该行为。另确认托盘「退出」在窗口已隐藏时仍能触发 `closeEvent` 并结束事件循环。
- **A9 角标样式表解析警告**：启动桌宠时控制台打印两行 `Could not parse stylesheet of object StatusBadge`。初判为 QSS 与半透明顶层窗不兼容，且本机未能复现；改用 `qInstallMessageHandler` 捕获 Qt 消息后确认根因是样式表最后一段为普通字符串，`}}` 未按 f-string 转义，实际多输出一个右花括号。修正为单个 `}`，并新增捕获 Qt 消息的回归测试（修正前失败、修正后通过）；ruff 与 147 条桌宠端用例通过，真实 `main.py` 运行 8 秒控制台 0 条解析警告（旧样式表对照为 2 条）。
- **角标与桌宠独立显隐（2026-10-23）**：原 A6 行为把 Claude / Codex 角标与桌宠绑定在同一显隐状态，隐藏桌宠会连带隐藏角标。改为 `hide_to_tray()` 只隐藏桌宠与气泡，角标由用户开关与状态驱动共同决定；右键与托盘新增「显示状态角标」开关并持久化 `status_badges_visible`。实现时避免把方法命名为 `set_enabled`（会覆盖 `QWidget.setEnabled` 的控件禁用语义），改用 `set_user_visible`；原 A6 回归用例随之改为断言「隐藏桌宠后角标仍显示」。ruff check/format 与本分支 208 条桌宠端用例通过（develop 基线 201 + 新增 7）。自查复盘另修正新增默认值用例直接读取仓库 `config.json` 的隔离缺陷：改为 monkeypatch `pet.config.BASE_DIR` 到 tmp_path，并补持久化往返与启动恢复用例，避免用户关闭角标后本地测试变红。

### 5.4 已知局限

- `window`、`sprite`、`hotkey_dialog` 等 Qt 界面层不做无头 UI 自动化，按 §1 策略由 `scripts/smoke_test.py` 与人工验证覆盖。
- 久坐检测的 Windows 分支（`ctypes` `GetLastInputTime`）在 Linux CI 下不覆盖，仅由本地人工验证。
- 真实微信账号、手机接收、C3 真机联调、公网部署复现与跨机器时钟同步均未纳入自动化结论；Mock 与 curl 证据不替代这些验收。
- 故障注入以固定时钟、受控异常和状态恢复模拟，不宣称执行过操作系统强制断电测试。
- A2 的真实 LLM 验收中，模型把「明天下午三点」解析为过去的日期（`2026-10-11`）；工具层只规整显式时间、不纠正模型给出的绝对日期，相对日期正确性依赖模型自身的时间认知，当前未做服务端日期注入。原始记录保留在 `docs/evidence/a-desktop/`。
