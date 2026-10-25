# 后端接口与实时事件契约（B1–B4）

关联 [Issue #5](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/5) 与 [Issue #6](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/6)。
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

复现方法见 [测试文档](testing.md) §3.3、§5.2 与 `scripts/smoke_backend_ws.py`。实现参考：
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
迁移、备份与恢复使用 `scripts/backup_backend_db.py`，调度故障用例见 [测试文档](testing.md) §3.2，量化口径见 [quality-baseline](quality-baseline.md)。单 worker 约束见本文“一致性、失败与兼容”。

## A4：重复投递处理（2026-10-12 用户授权补全）

桌宠在窗口生命周期保存最近 1024 个已处理 event_id，按最近使用顺序淘汰；
断线重连复用缓存，重复通知不再拉正文、弹气泡或启动语音。重新安排提醒的新事件 ID 正常显示。
只处理版本 1、已知类型、长度 1–128 的字符串事件 ID 及正整数资源 ID；非法信封直接忽略。
处理成功后记录 ID；处理抛出异常则允许后续重试。
缓存不是业务数据库，不持久化提醒内容；窗口重建、应用重启或容量淘汰后可能再次显示旧事件，
不承诺跨重启恰好一次。未来若要跨重启去重，需要另行引入持久消费游标/确认协议。

本轮显示延迟从计划到期计算，联调使用 1 秒扫描，30 样本目标均不超过 5 秒；
默认 30 秒单独报告。决定依据与原条件冲突见 [质量口径](quality-baseline.md)。

## B3：微信登录与订阅消息

所有请求携带 `X-API-Key`；本人提醒创建/查询、订阅登记与查询另需 `Authorization: Bearer <session_token>`。实现分为 `WeChatClient`（HTTP 适配）、`wechat_store`（事务与状态）、`WeChatDispatcher`（重试决策）与路由四层，微信与桌面扫描各用独立后台循环。

C3 修复新增带 Bearer 的本人提醒创建/查询、event_id 校验和消息落地页；日程改期、清除和删除与关联提醒处理在同一事务完成。同一时刻的格式变化不生成新事件。接口清单、恢复规则及兼容边界见 [C3 接口与恢复说明](c3-subscription.md)。现有 REST/WS 事件格式保持兼容。

### 登录

`POST /api/wechat/login`，请求 `{"code":"wx.login 获取的新 code"}`；成功返回：

```json
{"user_id":1,"openid":"微信用户标识","session_token":"服务端随机会话","expires_in":7200}
```

响应 `Cache-Control: no-store`。同一 AppID/openid 重复登录复用 user_id 并撤销旧会话；本地库只保存 SHA-256 会话摘要，不返回 `session_key`、AppSecret 或微信 access_token。code 失效返回 401，上游不可用或畸形响应返回脱敏 502。

### 提醒归属与订阅登记

管理接口 `POST /api/reminders` 保留可选 `wechat_user_id`，`phone`/`both` 必须绑定收件人并登记授权后才发送微信。C3 小程序使用 `POST /api/wechat/reminders`，提交 `task_id`，由后端从 Bearer 会话确定身份并在事务中创建或复用本人 phone 提醒；不由客户端指定收件人。小程序在用户主动操作后调用：

- `POST /api/wechat/subscribe`，请求 `{"reminder_id","request_id"(UUID),"template_id","result":"accept|reject|ban|filter","event_id"(可选)}`。C3 必传 `event_id`，旧客户端省略时保持原契约；事件已变化返回 409 `reminder_event_changed`。同一网络重试复用原 `request_id`；内容变化或同一事件重复登记返回 409。`accept` 初始为 pending，其余为 rejected 且不发送。
- `GET /api/wechat/subscriptions/{reminder_id}` 返回本人当前仍拥有的该提醒的订阅历史，记录包含 `event_id`；无记录或非本人时返回空数组。C3 按当前事件匹配，不能用历史 sent 表示当前事件已发送。
- `GET /api/reminders/{id}/delivery` 在 B2 字段外新增 `wechat` 数组。

| 情况 | HTTP |
|---|---|
| 缺失或错误 API Key / Bearer 会话 | 401 |
| 非本人提醒或不存在 | 404 |
| 仅 pc 渠道、提醒已完成、request_id 内容冲突 | 409 |
| 模板不匹配、额外 openid 字段、非 UUID、非法收件人 ID | 422 |

### 状态、重试与完成语义

`pending → sending → sent / retry / failed / uncertain`；`uncertain` 覆盖超时、响应不完整、取消及发送成功但写库失败，可能已消耗订阅机会，不自动重发。43101/40037/47003 等明确拒绝为 failed。token 过期前刷新、并发刷新合并，微信返回 40001/40014/42001 时只刷新重试一次。`pc` 沿用 B2；`phone` 仅微信成功后置 done=1；`both` 的 done 仍由桌面成功驱动，微信状态独立，不能以单一 done 推断双渠道均成功。修改提醒会取消旧待发授权并生成新事件，新事件需重新登记。

### 配置

| 参数 | 默认 | 说明 |
|---|---|---|
| `WX_ENABLED` | false | 显式启用微信渠道 |
| `WX_APPID`、`WX_SECRET` | 空 | 小程序身份与服务端凭证 |
| `WX_TEMPLATE_ID` | 空 | 账号实际可用的订阅消息模板 |
| `WX_TEMPLATE_FIELDS` | {} | JSON 字段映射，如 `{"thing1":"title","time2":"remind_at"}` |
| `WX_MINIPROGRAM_STATE` | developer | developer / trial / formal |
| `WX_TIMEOUT_SECONDS` | 10 | 单次 HTTP 请求上限 |
| `WX_SESSION_TTL_SECONDS` | 7200 | 本地会话有效期，60–86400 秒 |

字段名必须匹配真实模板。目前支持 `thingN` 对应 `title`/`body`，`timeN`/`dateN` 对应 `remind_at`；文本取前 20 个字符，时间按 `REMINDER_NAIVE_OFFSET_MINUTES` 显示，格式为 `YYYY-MM-DD HH:MM`。其他字段类型尚未实现，不能套用示例假装模板兼容。

缺少身份配置时微信接口返回 503；缺少模板或映射时订阅返回 503。启动时幂等创建 `wechat_users`/`wechat_sessions`/`wechat_subscriptions` 并为 reminders 增加可空外键，迁移版本 2；不自动绑定已有提醒，也不生成升级备份。

## B4：天气与搜索

新增 `GET /api/tools/weather?city=...` 与 `GET /api/tools/search?q=...&limit=3`，均需 `X-API-Key`。

| 接口 | 参数约束 |
|---|---|
| weather | `city` 必填 1–80 字符，支持中文、字母、空格及地名标点；拒绝 URL、IP、控制字符与 wttr 特殊命令 |
| search | `q` 必填 1–200 字符，禁止控制/格式字符；`limit` 为 1–5，默认 3 |

统一返回 `{status, query, provider, summary, source_url, fetched_at, observed_at, results}`；`status` 为 `ok`，搜索确实无结果为 `empty`。天气单独保留上游 `observed_at`，搜索为 null；成功响应 `Cache-Control: no-store`，不缓存、不持久化。

| HTTP | 错误或行为 |
|---|---|
| 401 | 缺失或错误的 X-API-Key |
| 422 | 参数不合法，不访问上游 |
| 502 | 网络失败、非成功 HTTP、结构变化、超大响应、编码或压缩损坏 |
| 503 | 后端 Key 未配置，或上游 202/403/429、验证码页面 |
| 504 | 总请求超时（含等待并发槽位与读取响应） |

业务失败体为 `{"detail":"稳定错误码"}`（如 `upstream_timeout`、`search_challenge`），不返回上游正文、异常 URL 或代理凭证。资源与配置：`WEB_QUERY_TIMEOUT_SECONDS` 默认 8、`WEB_QUERY_MAX_BYTES` 默认 262144（原始与解压后分别限制）、`WEB_QUERY_MAX_CONCURRENT` 默认 4。目标地址固定在 config（HTTPS 的 wttr.in 与 html.duckduckgo.com），不跟随重定向、无自动重试；只解码 gzip/deflate/identity 并限制解压输出；丢弃非 HTTP(S)、内网 IP、localhost、带账号口令的链接，不抓取结果页面。现有桌面本地联网工具接入方式待 A/B 评审，本次不修改其调用路径；示例见 `scripts/smoke_backend_web_query.py`。
