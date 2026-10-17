# 测试文档

## 1. 测试策略

按「纯逻辑 → 无界面 UI → mock 隔离外部依赖」分层：

- **纯逻辑单测**：配置、记忆、人设、气泡折行、时间规整、图片缩放等无副作用逻辑，直接断言。
- **无界面 Qt 测试**：通过 `QT_QPA_PLATFORM=offscreen` 在无显示环境跑 Qt 组件；CI 另用 `xvfb-run` 提供虚拟 X 显示器，供 `pynput` 探测 X 连接。
- **mock 隔离网络**：LLM 提供者用假客户端替换，验证流式拼接、回调与异常包装，不真正联网；后端视觉解析用假 HTTP 响应替换，覆盖超时/上游报错等分支。
- **接口级测试**：后端用 FastAPI `TestClient` 走真实路由 + 临时 SQLite，覆盖鉴权、CRUD、WebSocket 广播与调度器。

真实网络（LLM/TTS）与硬件（麦克风/whisper 模型）由 `scripts/smoke_test.py`、`scripts/smoke_backend_ws.py`、`scripts/smoke_backend_scheduler.py` 与人工验证覆盖，不进入自动化单测。

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

CI（GitHub Actions）在 main/develop 的 push 和 PR 时执行上述步骤，并额外运行后端 WebSocket、调度器与微信 Mock 三个冒烟脚本、`detect-secrets` 密钥扫描与 `pip-audit` 依赖漏洞审计。桌面人工冒烟脚本不在 CI 中运行。

## 3. 测试用例清单

### 3.1 桌宠端（`tests/`，106 个用例）

| 文件 | 覆盖点 | 用例数 |
|---|---|---|
| `test_config.py` | 配置默认值、环境变量覆盖、config.json 字段、健康项、LLM 生成参数、更新/人设方法 | 7 |
| `test_memory.py` | 增删顺序、轮数裁剪、持久化往返 | 4 |
| `test_persona.py` | 人设提示词包含名字/性格/语气 | 1 |
| `test_providers.py` | 流式拼接与回调、异常包装、tool_calls 回传（空/单/多条）、生成参数、工厂、LLM 门面 | 10 |
| `test_bubble.py` | 折行纯函数（空/超长/换行）、气泡流式追加 | 4 |
| `test_agent.py` | 工具循环次数上限、最终流式回复、未知工具回传 | 3 |
| `test_backend_client.py` | REST 封装、鉴权头、绕过系统代理、非 JSON 2xx、CRUD、ws URL/事件解析 | 9 |
| `test_tools.py` | 工具注册表 schema、格式化缺字段、创建/更新/删除、联网失败、自然时间规整 | 14 |
| `test_timeparse.py` | 「今天/明天/后天 + 时刻」→ ISO、ISO/未知输入透传 | 6 |
| `test_health.py` | 久坐阈值、离座清零、周期重复、在座判定 | 6 |
| `test_ws_listener.py` | WebSocket 消息解析、重连、事件分发 | 6 |
| `test_event_dedup.py` | 实时事件去重缓存（重复事件抑制、过期淘汰、容量上限） | 15 |
| `test_hotkey.py` | 全局快捷键注册、组合键解析与触发 | 8 |
| `test_tts.py` | TTS 文本切分、音色参数、离线回退 | 6 |
| `test_image_utils.py` | 图片缩放/裁剪纯函数 | 5 |

合计 **106 个用例**，全部通过。

### 3.2 后端（`backend/tests/`，168 个用例）

| 文件 | 覆盖点 | 用例数 |
|---|---|---|
| `test_api.py` | 健康检查公开、缺/错 token 拒绝、课表/任务/提醒 CRUD 与部分更新 | 6 |
| `test_course_import.py` | 图片识别导入鉴权、未配置 503、成功解析、无课表 422、上游错误 502、超时 504、文件过大 413、批量落库（合法入库/非法跳过） | 14 |
| `test_db_migrations.py` | 建库、字段迁移、重复初始化幂等 | 4 |
| `test_scheduler.py` | 到期判定、30s 轮询、广播后标记完成、禁用开关、边界时间 | 33 |
| `test_vision.py` | 视觉模型响应解析、节次/周数映射、备注防臆造、异常降级 | 28 |
| `test_ws.py` | WebSocket 鉴权、广播推送、断线清理、事件格式 | 24 |
| `test_wechat.py` | 登录会话、授权归属、缓存/刷新、幂等发送、故障恢复、迁移及渠道隔离 | 59 |

合计 **168 个用例**，Windows Python 3.13/3.10 均通过；B3 环境与原始记录见 [B3 报告](b3-test-report.md)。

## 4. 实验环境

| 项 | 值 |
|---|---|
| OS | Windows 11 Home（开发）/ Ubuntu latest（CI） |
| Python | 3.14.5（开发）/ 3.12 与 3.10（CI 后端矩阵）/ 3.12（CI 桌宠） |
| 关键依赖 | PyQt6 6.11、openai 3.31、edge-tts 7.3、faster-whisper 1.2、pytest 9.1 |
| 测试框架 | pytest 9+、`QT_QPA_PLATFORM=offscreen`（CI 叠加 `xvfb-run`） |

## 5. 结果

以下保留 B3 之前的 CI 实测记录（Ubuntu，Python 3.12），用于历史对照；B3 新结果见下方增量，不将这些历史数值当作当前完整版本的覆盖率：

```
桌宠端：106 passed，ruff check main.py pet tests → All checks passed!
        行覆盖率 50%（pet/ 共 1696 语句、849 覆盖）

后端：  109 passed，ruff check . ../scripts → All checks passed!
        行覆盖率 92%（app/ 共 819 语句、62 未覆盖）
```

覆盖率较高的模块：`providers` 97%、`tts` 98%、`event_cache` 94%、`backend_client` 93%、
`tools` 93%、`memory` 93%、`agent` 91%、`llm` 89%、`config` 83%、
`timeparse`/`image_utils`/`persona`/`paths` 100%；
后端 `scheduler`/`schemas`/`main`/`logging_config`/`reminder_time` 100%、`push_service` 99%、`course_import` 98%、`db` 96%。

**已知局限**：

- `window`（23%）、`sprite`（14%）、`hotkey_dialog`（0%）等 Qt 界面层不做无头 UI 自动化，
  按 §1 策略由 `scripts/smoke_test.py` + 人工验证覆盖。
- 久坐检测的 Windows 分支（`ctypes` `GetLastInputTime`）在 Linux CI 下不覆盖，仅由本地人工验证。
- Live2D 模块依赖 `PyQt6-WebEngine`，在 Linux CI 运行时未加载，故不计入 CI 覆盖率统计。

### B3 增量（2026-10-14）

本地后端 168 项通过，行覆盖 94.19%（1153 语句、1086 覆盖）；桌面仍为 106 项通过。微信新增四模块行覆盖均为 100%，不代表分支覆盖或真机接收通过。Mock 30 次发送只取一次 token，重复登记未造成额外发送。[PR #29](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/29) 提供当前远端检查记录；详细用例、基线、限制和证据见 [B3 测试报告](b3-test-report.md)。

## B4 分支验证增量（2026-10-15）

本分支从 `42a95ba` 开始，新增 `backend/tests/test_web_query.py` 的 63 项用例，当前后端 172 项、桌面 106 项均通过。旧章节中的 109 项是 B4 之前的记录；B3 在另一 PR 中，不能将其用例计入本分支。B4 CI 新增 `scripts/smoke_backend_web_query.py`（真实 curl、Mock 上游），详细覆盖、环境和真实网络失败/修正见 [B4 报告](b4-test-report.md)。

人工验收后的日志修正又新增 `backend/tests/test_logging_config.py` 的 12 项回归，当前后端总数为 184，Python 3.10 / 3.13 均通过。用例使用 Uvicorn 真实格式器，覆盖彩色插值、访问日志字段及查询脱敏；另有真实服务器日志验证。上段 172 项是修正前快照，具体前后结果与证据见 B4 报告末节。
