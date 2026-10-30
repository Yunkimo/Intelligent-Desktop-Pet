# 任务书：成员 B —— 后端服务

> 把本文件直接交给 AI 编程助手（如 Claude Code），即可按此开工。先读第 1、2、3 节，再按第 4 节顺序逐项完成。

## 1. 项目背景（agent 必读）

「智能桌宠」是期末课设项目，三端架构：

```
桌宠端（成员 A）  ↔  后端（你负责）  ↔  小程序（成员 C）
   PyQt6 + agent      FastAPI + SQLite      微信小程序
   HTTP REST + WebSocket                    HTTP REST + WebSocket
                                    后端 → 微信订阅消息（离线推送）
```

- **后端是唯一数据源**：课表、日程、提醒都存 SQLite，三端读写同一份数据。
- 你的端是「数据中心 + 调度中枢」：提供 REST CRUD、WebSocket 实时广播、到期调度、微信订阅消息推送。

## 2. 你负责的范围

| 编号 | 任务 | 说明 |
|---|---|---|
| B1 | WebSocket 广播 | `/ws` 端点 + `push_service.broadcast()` |
| B2 | 调度器 | 每 30s 查到期 reminder → 触发广播 |
| B3 | 微信订阅消息 | `wx.login` + `subscribeMessage.send` |
| B4 | 联网查询接口 | 天气/搜索封装（供桌宠 agent 调用） |
| B5 | 日程与提醒联动 | #33，核心已实现待评审；C6 负责交互收尾 |
| B6 | 数据变更事件补齐 | #34，复用 B1；C7 负责消费与页面刷新 |
| B7 | 学期日历与课前提醒 | #35，复用 B2；C8 负责设置与展示 |

## 3. 当前状态与起点

- 仓库：本仓库（`origin = https://github.com/Yunkimo/Intelligent-Desktop-Pet`），分支模型 `main` / `develop` / `feat/*`。
- 现状：`backend/` 已有 **M1 后端骨架**（已完成、6 单测通过）：
  - `app/main.py`：FastAPI 应用，lifespan 初始化 DB，挂载路由 + `/api/health`
  - `app/config.py`：读 `.env`（`API_TOKEN`、`DB_PATH`）
  - `app/db.py`：sqlite3 建表 + CRUD（courses / tasks / reminders）
  - `app/auth.py`：`X-API-Key` 鉴权依赖（未配置 503 / 不匹配 401）
  - `app/schemas.py`：pydantic 模型
  - `app/routers/`：courses / tasks / reminders 三组 REST
  - `tests/`：pytest 6 例
- 你的工作分支：从 `develop` 切出 `feat/backend-realtime`。

## 4. 任务清单

### B1. WebSocket 广播（关键路径，优先做）
- 新建 `app/routers/ws.py`：`GET /ws`，用 query 参数 `?token=` 校验，注册连接。
- 新建 `app/push_service.py`：维护连接集合，提供 `broadcast(event: dict)` 广播 JSON 事件（`task.created` / `reminder.due` / `course.created`…）。
- 在 `main.py` 挂载 ws 路由。
- 依赖：M1（已就绪）。
- 验收：两个客户端（`websocket-client` 或 `wscat`）同时收到同一事件；token 错误时拒绝连接。

### B2. 调度器
- 新建 `app/scheduler.py`：asyncio 后台循环，每 30s 查 `done=0` 且 `remind_at` 已到期的 reminders → 调 `push_service.broadcast` 发 `reminder.due` → 标记 `done=1`。
- 在 `main.py` lifespan 启动 / 停止该循环。
- 依赖：B1。
- 验收（2026-10-12 按用户授权统一）：联调配置扫描 1 秒，加 `remind_at=now+60s` 提醒，
  到期后 5 秒内显示气泡且该提醒标记为 done；30 条样本均限时显示，故障重试不会重复通知。
  默认 30 秒扫描单独报告延迟，不套用五秒目标。原“创建后 60 秒内”的冲突及失败数据保留在 [测试文档](../testing.md) §5.3。

### B3. 微信订阅消息
- 新建 `app/routers/wechat.py`：`POST /api/wechat/login`（`code`→`openid`）、`POST /api/wechat/subscribe`（记录订阅授权）。
- 在 `db.py` 新增表 `wechat_users(id, openid, created_at)`。
- 扩展 `push_service`：`send_wechat_msg(openid, ...)` 调微信 `subscribeMessage.send`；`access_token` 本地缓存 + 自动刷新。
- `config.py` 增读 `WX_APPID` / `WX_SECRET` / `WX_TEMPLATE_ID`。
- 依赖：M1。
- 验收：模拟订阅后触发提醒，微信收到订阅消息（需小程序端 C3 联调；先用 mock 做单测）。

### B4. 联网查询接口（可选）
- 封装天气（`wttr.in`，免 key）与搜索（DuckDuckGo，免 key），返回摘要文本。
- 供桌宠 agent 工具调用；实现位置（后端接口 vs 桌宠端本地）与成员 A 对齐。
- 依赖：M1。
- 验收：curl 返回天气/搜索摘要。

### B5. 日程与提醒联动（Issue #33）

- 目标：v1.0.0 后续迭代，版本号由团队确定，不追记到已发布的 v1.0.0。
- 沿用 SQLite、现有调度状态与事务；创建带 remind_at 的日程时原子创建一条 PC 提醒。
- 改期和未发送内容同步；完成、清空提醒时间、删除时失效旧计划，独立提醒不受影响。
- 重开日程重新安排；过去时间下一轮扫描尝试发送；历史数据启动不批量补发，明确编辑时的修复规则。
- A 的日程工具与 C 的日程页面只需保存 tasks；微信仍通过 C3 按用户授权，不隐式订阅。
- 验收覆盖事务回滚、重复请求、等价时间、旧领取失效、历史兼容及 A/C 调用链；测试、格式和密钥检查通过后交其他成员评审。
- 本次分支 `feat/backend-task-reminders`；实现/边界及复现步骤见 [B5 核验说明](../b5-verification.md)。

### B6. 数据变更事件补齐（#34，协作 C7）

- 已有广播、提交后通知及故障隔离直接复用；只新增更新/删除及提醒资源事件，覆盖 B5 联动和批量操作。
- B 交付信封契约、发布入口和事务/异常测试；C 扩展现有白名单与页面订阅，复用去重/重连/节流。
- 验收需真实跨端更新、删除、完成和重开，失败不发成功事件，推送失败不回滚保存。

### B7. 学期日历与课前提醒（#35，协作 C8）

- B 实现学期持久化、日期周次/课程实例、唯一计划及失效、单次停调课和停机恢复；复用 B2，不另建调度器。
- C 实现云端学期设置、浏览周次、停调课及提醒状态展示；已有本地周次过滤不重新开发。
- 未配置不生成提醒；PC 先行，微信仍要求 B3/C3 显式授权。A 的查询/展示适配由 A 协作。

### B/C 共用范围与状态

B5 已推送实现见 `b59fd0f`，不重写；C6 尚需日程提醒状态与提示改进。B6/B7 只交付已有能力之外的增量。
完整已有能力清单、逐项负责人、验收和依赖见 [B/C 分工核对](BC-followup-scope.md)，对应 C 任务书 C6/C7/C8。
以上为 v1.0.0 后续迭代，不追记为旧版本已交付；成员评审和真实界面验收缺失时如实保留。

## 5. 技术约定（必须遵守）

- 沿用现有风格：标准库 `sqlite3`（**无 ORM**）、pydantic 模型、FastAPI 依赖注入鉴权、中文 docstring。
- 密钥（`WX_APPID` / `WX_SECRET`）放 `.env`，**绝不提交**。
- WebSocket 鉴权用 query 参数 `?token=`。
- 新增依赖在 `backend/requirements.txt` 追加（如 `websockets`）。

## 6. 分支与提交

- 分支：`feat/backend-realtime`（从 `develop` 切）。
- 原子提交 + Conventional Commits：`feat(backend): ...`、`test(backend): ...` 分开。
- B1～B7 每个任务单独提交，完成后开 PR 到 `develop`。
- 标题必须含中文：`type(backend): 中文简述`，正文可中英混用；使用成员 B 本人 Git 身份，不添加 AI 协作者署名。

## 7. 验证方式

- `pytest` 全绿（为 ws/push/调度新增单测；微信接口用 mock，不真调）。
- 用 `websocket-client` 脚本或 curl 验证广播、调度、订阅接口。

## 8. 协作与依赖

- **B1 是关键路径**：成员 A 的 A4、成员 C 的 C2 都要等 B1，请优先完成并尽快合入 `develop`。
- B3 需小程序端（C3）联调；先写 mock 单测，接口就绪后联调。
