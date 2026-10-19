# 任务书：成员 A —— 桌宠端智能体

> 把本文件直接交给 AI 编程助手（如 Claude Code），即可按此开工。先读第 1、2、3 节，再按第 4 节顺序逐项完成。

## 1. 项目背景（agent 必读）

「智能桌宠」是期末课设项目，三端架构：

```
桌宠端（你负责）  ↔  后端（成员 B）  ↔  小程序（成员 C）
   PyQt6 + agent      FastAPI + SQLite      微信小程序
   HTTP REST + WebSocket                    HTTP REST + WebSocket
                                    后端 → 微信订阅消息（离线推送）
```

- **后端是唯一数据源**：课表、日程、提醒都存后端 SQLite，三端读写同一份数据。
- 五大能力：AI 学习生活规划、课表提醒、健康关怀（久坐提醒）、多端提醒、可联网查询。
- 你的端是「交互入口 + 智能体大脑」：用户用文字/语音跟宠物对话，宠物靠大模型 + 工具调用去查课表、排日程、设提醒。

## 2. 你负责的范围

| 编号 | 任务 | 说明 |
|---|---|---|
| A0 | 导入桌宠基线代码 | 把旧桌宠代码迁入本仓库（一次性） |
| A1 | BackendClient | 桌宠用 httpx 调后端 REST |
| A2 | Agent 工具调用 | 大模型 function calling + 工具循环 + 联网查询 |
| A3 | 健康关怀 | 久坐 / 喝水 / 休息提醒 |
| A4 | 实时接收 | WebSocket 接收后端广播事件 |

## 3. 当前状态与起点

- 仓库：本仓库（`origin = https://github.com/Yunkimo/Intelligent-Desktop-Pet`），分支模型 `main`（主干）/ `develop`（开发）/ `feat/*`（特性）。
- 现状：`develop` 上已有 `backend/`（M1 后端骨架，已完成、测试通过）和 `pet/`（桌宠基线，已迁入）。**A0 已完成，直接从 A1 开始。**
- 桌宠旧代码位置（本机）：`C:\Users\yunkimo\Desktop\Intelligent Desk\`，含 `pet/`、`main.py`、`config.json`、`requirements.txt`、`.env.example`、`assets/` 等。
- 你的工作分支：从 `develop` 切出 `feat/desktop-agent`。

## 4. 任务清单

### A0. 导入桌宠基线代码 ✅ 已完成（`pet/` 基线已迁入 develop，跳过本步）
- 从 `C:\Users\yunkimo\Desktop\Intelligent Desk\` 拷贝以下到本仓库根目录：
  - `pet/`（整个目录，排除 `__pycache__/`）
  - `main.py`、`config.json`、`requirements.txt`、`.env.example`
  - `assets/`（如存在；`assets/` 体积大时先和团队确认是否用 Git LFS 或单独分发）
- **必须排除**：`.env`（含密钥）、`data/`、`build/`、`dist/`、`*.mp3`、`__pycache__/`。
- 验收：`python main.py` 能启动桌宠窗口（无后端也能纯聊天）。

### A1. BackendClient（httpx REST 客户端）
- 新建 `pet/backend_client.py`：`BackendClient` 类，封装 `get_courses / create_task / list_tasks / create_reminder` 等方法，自动带 `X-API-Key` 头，`base_url` 读配置。
- 改 `pet/config.py`：**新增** `BACKEND_URL`、`API_TOKEN` 字段。注意与已有 `llm_api_key` / `llm_base_url` / `llm_model` 区分：LLM 密钥在根目录 `.env`（3 字段），后端 token 是另一套（放 `backend/.env`），形象/语音/记忆在 `config.json`。
- 依赖：后端 M1（**已就绪**）。
- 验收：桌宠启动后能在气泡里显示后端返回的课表/日程（加一个临时调试入口即可）。

### A2. Agent 工具调用
- 改 `pet/providers.py`：现有抽象方法是 `stream_chat(messages, on_chunk=None)`（**不是** `chat`），在此基础上**新增** `chat_with_tools(messages, tools, on_chunk=None)`；`OpenAICompatProvider` 用 openai SDK 的 `tools=` / `tool_choice="auto"`。
- 新建 `pet/agent.py`：`Agent` 工具循环——非流式请求拿 `tool_calls` → 执行工具 → 结果喂回 → 限次（≤3）→ 最终流式回复。
- 新建 `pet/tools.py`：工具注册表 `TOOLS`（name → JSON schema + callable）：查课表 / 加改删日程 / 设提醒 / 联网查询（天气 wttr.in、搜索 DuckDuckGo `ddgs`，均免 key）。
- 改 `pet/llm.py`：`LLMClient` 门面现有方法 `chat`（内部转发 `provider.stream_chat`），**新增** `chat_with_tools` 同名透传（保持门面统一）。
- 改 `pet/worker.py`：`ChatWorker` 增加 `tools` 与 `status(str)` 信号（工具执行时发出「正在安排日程…」），`run()` 改走 agent 循环。
- 改 `pet/persona.py`：`build_system_prompt` 追加工具使用说明（何时查课表/设提醒，回复要简短）。
- 改 `pet/window.py`：`_start_chat` 传入 `TOOLS`。
- 依赖：A1。
- 验收：对话「帮我加一条明天上午复习英语的日程」→ 后端 DB 出现对应记录；「查一下明天天气」→ 返回实时天气。

### A3. 健康关怀
- 新建 `pet/health.py`：`HealthMonitor(QObject)`，`QTimer` 定时 + `ctypes` 读 Windows `GetLastInputTime` 判定久坐；超阈值触发喝水/休息提醒（气泡 + TTS，可选推手机）。
- 改 `pet/config.py`：`config.json` 增读 `health_enabled` / `water_interval_min` / `rest_interval_min`，写回直接复用 `Settings` 已有的 `_save_json`。
- 依赖：无（纯本地，可与 A1 并行）。
- 验收：把间隔临时调成 1 分钟，停止操作电脑后看到喝水提醒。

### A4. 实时接收（依赖成员 B 的 B1）
- 在 `pet/backend_client.py` 内新增 `WsListener(QThread)`：用 `websocket-client` 连后端 `/ws`，收到事件 emit `event(dict)`。
- 改 `pet/window.py`：新增 `_on_backend_event`，`reminder.due` → `show_hint` + `_speak` + 形象反应（`avatar.react`）。
- 依赖：成员 B 的 B1（WebSocket 端点）。
- 验收（2026-10-12 按用户授权统一）：联调扫描 1 秒，计划到期后 5 秒内显示气泡；
  至少 30 条样本全部限时显示。语音另验证真实合成及播放器开始/结束，故障重发及断线重连只通知一次。
  原“创建后 10 秒内显示一个 10 秒后才到期的提醒”保留为历史冲突，原因及前后实测见 [测试文档](../testing.md) §5.3。

## 5. 技术约定（必须遵守）

- 沿用现有风格：**策略模式**（ChatProvider / 形象引擎）、**QThread + signal**、**`.env` + `config.json` 双源配置**、中文 docstring。
- 密钥（DeepSeek key、后端 `API_TOKEN`）一律放 `.env`，**绝不提交**。
- 后端交互用 `httpx`，实时用 `websocket-client`（在 `requirements.txt` 追加）。
- 复用现有：`show_hint` / `_speak` / `avatar.react`（`pet/window.py`）做提醒呈现；`Settings` 双源加载（`pet/config.py`）加字段。

## 6. 分支与提交

- 分支：`feat/desktop-agent`（从 `develop` 切）。
- 原子提交 + Conventional Commits：`feat(pet): ...`、`refactor(pet): ...`、`docs: ...` 分开。
- A0～A4 每个任务单独提交，完成后开 PR 到 `develop`。

## 7. 验证方式（端到端）

1. `python main.py` 启动桌宠，无后端也能聊天。
2. 起后端（`cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8001`），桌宠能读课表。
3. 对话新增日程 → 查后端 DB 确认写入。
4. 后端加到期提醒 → 桌宠收到 WebSocket 弹出（需 B1 就绪）。
5. 短间隔触发健康提醒。

## 8. 协作与依赖

- **A4 依赖 B1**（成员 B 的 WebSocket）；先做 A0→A3，A4 等 B1 就绪再做。
- REST 字段以 `backend/app/schemas.py` 为准，接口有调整时与成员 B 对齐。
