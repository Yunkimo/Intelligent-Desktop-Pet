# 后端实时事件契约（B1 已合并；B2 补充待 A/C 评审）

关联 [Issue #5](https://github.com/Yunkimo/IDP/issues/5) 与 [Issue #6](https://github.com/Yunkimo/IDP/issues/6)。
B1 已由 PR #16 合并；B2 的时间、状态与验收口径补充仍需 A/C 评审，不把本地验证当作三端验收。

## 连接与鉴权

- 路径：`ws://<后端地址>:8001/ws?token=<URL 编码的 API_TOKEN>`。
- 必须发起 HTTP Upgrade；普通 `GET /ws` 返回 404，不表示连接成功。
- 成功握手为 HTTP 101。缺失、空、错误、重复 token，或服务端未配置 `API_TOKEN`，
  均在接受连接前拒绝，真实 Uvicorn 返回 HTTP 403。
  ASGI TestClient 报 `WebSocketDisconnect(1008)`，不要混淆这两种观察方式。
- 同一演示 token 可连接多个客户端，各连接独立注册。断开后重连是新连接。
- 这是单用户受控演示的共享密钥，没有用户隔离、到期会话或刷新令牌。
  更换密钥并重启服务可撤销现有连接；公网发布前另行评审会话、TLS 和限流方案。
- 应用不接收客户端业务消息；发送文本或二进制数据帧将以 1008 关闭。
  WebSocket 协议层 ping/pong 由 Uvicorn 处理。
- 发送失败或超过配置超时移除连接，尽力以 1013 关闭；服务退出以 1001 关闭。
  已断网时客户端未必能收到 close 帧，应按断线处理。

## 事件信封

每条事件是一个 UTF-8 JSON 文本帧；同一次广播所有接收端获得相同 `event_id`。

| 字段 | 类型 | 语义 |
|---|---|---|
| `version` | 整数，当前为 1 | 不兼容变更递增版本，并先经 A/C 评审 |
| `event_id` | 非空字符串，生成时为 UUID | 一次逻辑事件的标识；接收端可去重 |
| `type` | 字符串 | 当前 schema 支持下表三类事件 |
| `occurred_at` | 带时区的 ISO 8601 字符串 | 服务端产生通知的时间，默认 UTC；不是提醒计划到期时间 |
| `data.id` | 正整数 | 由 `type` 确定资源类别的资源 ID；通知不包含业务正文 |

| `type` | 当前产生位置 | 获取状态 |
|---|---|---|
| `task.created` | `POST /api/tasks` 提交 SQLite 成功后 | `GET /api/tasks` |
| `course.created` | `POST /api/courses` 提交 SQLite 成功后 | `GET /api/courses` |
| `reminder.due` | B2 到期调度器领取提醒后 | `GET /api/reminders` |

样例（ID 与时间仅用于说明）：

```json
{"version":1,"event_id":"e2277dd9-8672-4d52-8e04-ec16845c3021","type":"task.created","occurred_at":"2026-10-11T08:00:00Z","data":{"id":1}}
{"version":1,"event_id":"1f6be7de-42d4-444a-9c4c-d6ed531958bd","type":"course.created","occurred_at":"2026-10-11T08:00:01Z","data":{"id":2}}
{"version":1,"event_id":"48a930c8-66f0-4f46-88f6-61a9b6947053","type":"reminder.due","occurred_at":"2026-10-11T08:00:02Z","data":{"id":3}}
```

服务内部调用入口：`await app.state.push_service.broadcast(event)`，返回成功执行发送的连接数。
输入先经 `Event` 校验，无效输入不发送；不是可被客户端调用的 HTTP 发布接口。
生产者若重试同一事件，应复用完整信封，包括 `event_id`。

## 一致性、失败与兼容

- 后端是唯一持久化数据源；事件只是提示。收到事件后用 REST 读取状态。
- 先建立连接，再读取初始快照；重连后重新拉取。客户端忽略未知字段、未知事件类型；
  遇到不支持的版本先刷新 REST，并记录兼容问题。
- B1 不提供历史补发、确认回执、持久队列或可靠送达保证。离线、重启或崩溃窗口会丢事件。
  `send` 成功也不能证明客户端展示。不能宣称 exactly-once。
- 一次广播并发发送给各连接，每条连接的发送串行化。并发 REST 请求间不承诺全局事件顺序。
- 推送失败不回滚已提交的 SQLite 写入，REST 仍返回原有 201 及资源正文。
  HTTP 本身断线时先查 REST 确认，不能仅因未收到事件就重试写入。
- B1 仅对日程和课表的创建发送事件；更新、删除、提醒创建没有新增广播。
- 固定单进程、单 worker。多 worker 的连接集合互不可见，不可直接扩容后声称广播等价。
- `WS_SEND_TIMEOUT_SECONDS` 默认 2；`WS_CLOSE_TIMEOUT_SECONDS` 默认 1。
  含锁等待的单连接发送超过上限会被移除；清理另有关闭上限。二者都必须为正有限秒数。
  环境变量优先于 `backend/.env`，最后使用默认值。
- Uvicorn 的应用日志移除 URL 整个 query。反向代理、监控和客户端日志仍需独立脱敏，
  禁止记录完整连接 URL；调试级第三方协议日志不在本次脱敏保证内。

复现方法见 [后端 WebSocket 验证报告](test-report.md)。实现参考：
[FastAPI WebSockets 官方文档](https://fastapi.tiangolo.com/advanced/websockets/)。

## B2：提醒时间与调度状态（待评审补充）

- `POST /api/reminders` 与 `PUT /api/reminders/{id}` 的 `remind_at` 必须是含 `T` 的有效 ISO 日期时间。
  带时区输入按其偏移转换；兼容旧客户端无时区输入，按 `REMINDER_NAIVE_OFFSET_MINUTES`（默认 480，即 UTC+8）解释。
  返回和持久化统一为带 `+00:00` 的 UTC 文本。无效输入返回 422，更新不可空字段时显式 null 返回 422。
- 调度只读取 reminders 表。设置 `tasks.remind_at` 不会自动创建 reminder；桌宠需调用已有创建提醒接口。
- 当前只处理 `channel=pc/both` 的 WebSocket 阶段；`phone` 等待 B3，不会被误标完成。
  `both` 本次只证明 WS 阶段，不能代表微信已发送。B3 必须独立建模手机渠道，不能以 done 筛掉手机待发任务。
- 自动写 `done=1` 表示本次逻辑提醒至少一次对某个 WS 连接的发送调用成功。
  它不表示所有连接收到、界面展示或用户阅读；人工 PUT done=true 仍可手动完成并取消调度。
- 没有连接、全部发送失败或总发送超时会保留 done=0，按指数退避重试；默认最多 3 次尝试。
  部分连接发送成功时不为其他失败连接整体重播。默认退避 30/60 秒，最高等待 300 秒，实际尝试还受扫描间隔影响。
- event_id 和 occurred_at 在同一次逻辑提醒的重试中保持稳定；occurred_at 为第一次领取时间。
  修改提醒内容会使旧领取失效并更新逻辑事件 ID。修改时间或渠道默认重新安排（done=0），
  显式 done=true 优先；仅修改已完成提醒的正文不重新发送。PUT done=false 可以重置失败任务及尝试次数。
- 在发送前检查领取是否仍有效，在写回时再次比较领取代号；编辑/删除与网络发送之间仍有无法原子化的窗口，
  客户端可能收到一条已过期通知，应拉取 REST 校正。发送成功但写回前崩溃时可能重发同一 event_id。
- 重启后按 30 秒领取租约恢复未完成尝试；崩溃发生在最后一次尝试时，租约到期转为 failed，done 保持 0。
  这是有限次数的至少一次尝试策略，不保证至少送达一次，更不是恰好一次送达。

新增鉴权诊断接口 `GET /api/reminders/{id}/delivery`：

| 字段 | 含义 |
|---|---|
| event_id | 当前逻辑提醒事件 ID |
| status | pending / sending / retry / sent / failed / cancelled |
| attempts | 已领取尝试次数，崩溃也计入 |
| last_error | null、no_clients、send_failed、send_timeout、attempts_exhausted 或 invalid_remind_at |
| next_attempt_at | UTC Unix 秒；0 表示未安排重试 |
| lease_until | UTC Unix 秒；0 表示无领取租约 |

接口使用既有 X-API-Key；未授权 401，ID 不存在 404；不返回内部领取代号。
恢复、迁移与单 worker 约束见 [B2 说明](b2-scheduler.md)，量化口径见 [quality-baseline](quality-baseline.md)。

## A4：重复投递处理（2026-10-12 用户授权补全）

桌宠在窗口生命周期保存最近 1024 个已处理 event_id，按最近使用顺序淘汰；
断线重连复用缓存，重复通知不再拉正文、弹气泡或启动语音。重新安排提醒的新事件 ID 正常显示。
只处理版本 1、已知类型、长度 1–128 的字符串事件 ID 及正整数资源 ID；非法信封直接忽略。
处理成功后记录 ID；处理抛出异常则允许后续重试。
缓存不是业务数据库，不持久化提醒内容；窗口重建、应用重启或容量淘汰后可能再次显示旧事件，
不承诺跨重启恰好一次。未来若要跨重启去重，需要另行引入持久消费游标/确认协议。

本轮显示延迟从计划到期计算，联调使用 1 秒扫描，30 样本目标均不超过 5 秒；
默认 30 秒单独报告。决定依据与原条件冲突见 [质量口径](quality-baseline.md)。

## B3 增量契约入口

微信登录、订阅登记与查询，以及提醒新增 `wechat_user_id` 的完整契约见 [B3 微信接口](b3-wechat.md)。现有 REST/WS 事件格式保持兼容；`phone`/`both` 必须绑定收件人并登记授权后才发送微信。`both` 的完成状态和双渠道结果须按该文档分别判断。
## B4 天气与搜索

新增带 X-API-Key 的 `GET /api/tools/weather?city=...` 和 `GET /api/tools/search?q=...&limit=3`。返回摘要文本、来源和查询时间；天气单独保留上游观测时间。输入限制、响应结构和 422/502/503/504 错误语义见 [B4 契约](b4-web-query.md)。现有桌面本地联网工具接入方式待 A/B 评审，本次不修改其调用路径。
