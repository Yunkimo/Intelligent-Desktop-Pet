# 小程序（任务书 C）

微信小程序端：手机查改课表/日程。今日页看当天课表与到期待办，课表页/日程页增删改，经 `utils/api.js` 对接后端 FastAPI（后端是唯一数据源）；`utils/ws.js` 订阅后端 WebSocket 事件实现实时刷新。

## 目录

| 路径 | 说明 |
|---|---|
| `project.config.json` | 微信开发者工具项目配置（`appid` 为占位 `touristappid`，请替换为你注册的 appid） |
| `app.js` / `app.json` / `app.wxss` | 全局入口（启动 WebSocket 适配层）、页面注册与 TabBar、全局样式 |
| `pages/index` | 今日课表 / 待办（按本周周次过滤、勾选完成、下拉刷新） |
| `pages/schedule` | 课表增删改 + 图片识别导入（按星期分组，周次支持 `1-16` / `1,3,5` 写法） |
| `pages/task` | 日程增删改（截止日期、勾选完成） |
| `utils/api.js` | `wx.request` / `wx.uploadFile` 封装：`baseUrl` 与 `X-API-Key` 集中配置于文件顶部 |
| `utils/ws.js` | WebSocket 事件适配层：连接/重连/节流/去重集中管理（契约见 `docs/api-contract.md`） |
| `utils/datetime.js` | 日期换算与本周周次工具（后端 `day_of_week` 1=周一 … 7=周日） |
| `config.example.js` | 复制为 `config.js` 填入 `baseUrl` / `apiKey`（`config.js` 已 gitignore，密钥不入库） |

## 本地联调

1. 启动后端：`backend/` 下 `python run.py`，健康检查 `GET /api/health`。
2. 微信开发者工具导入本目录（`miniprogram/`），把 `project.config.json` 的 `appid` 换成你自己的。
3. 复制 `config.example.js` 为 `config.js`，填入后端地址与 `backend/.env` 的 `API_TOKEN`。
4. 开发期后端是 http/ws：详情 → 本地设置 → 勾选「不校验合法域名」（上线路线见 `docs/deploy.md`，任务 C4）。
5. 编译预览：增删课表/日程，后端 SQLite 同步（验收：小程序增删课表，后端 DB 同步）。

## 实时刷新（C2）

- 启动时 `utils/ws.js` 连接 `ws://<后端>/ws?token=<API_TOKEN>`（由 `config.js` 的 `baseUrl`/`apiKey` 映射，页面不各自建连）。
- 收到 `task.created` / `course.created` / `reminder.due` 事件后，相关页面自动用 REST 重读（事件按契约校验、`event_id` 去重、400ms 节流合并）。
- 断线自动退避重连（1s→30s），重连成功与回到前台都会 REST 重读（后端无历史事件补发）。
- 验收：后端加数据（curl 或桌宠），小程序页面即时刷新；杀后端进程再拉起，小程序自动重连。

## 接口约定

- 所有请求带 `X-API-Key` 头，由后端校验；401 = Key 无效，503 = 后端未配置 `API_TOKEN`。
- 课表 `/api/courses`、日程 `/api/tasks`；字段以 `backend/app/schemas.py` 为准。
- 课表 `weeks` 在后端是 JSON 字符串（如 `"[1,2,3]"`），提交时传数字数组，展示由页面解析。

## 订阅提醒（C3）

- 入口：日程页带提醒时间的任务显示「订阅提醒」按钮，由用户主动点击触发微信一次性订阅授权。
- 流程： → （会话本地缓存，60s 提前过期，401 自动重登录幂等重试）→ 按任务查找/创建 phone 提醒 →  → （Bearer 会话头）。
- 结果语义：同意=登记意图；拒绝/取消/失败均如实提示；已订阅过的任务不重复弹框、不重复登记（本地状态跟随服务通知页开关）；微信记住拒绝时给出恢复指引。
- 应用内提醒补充：到期时后端广播 reminder.due，今日页「今日提醒」区展示 + 弹提示（小程序开着即可见）。
- 前置： 的 subscribeTemplateId 与  的 WX_* 配置（B3）；真机实收以微信服务通知为准。
- 验收：逻辑 15 项 + 契约 2 项测试见 tests/；真机五项验收记录见 Issue #11。

## 接口约定

- 所有请求带 `X-API-Key` 头，由后端校验；401 = Key 无效，503 = 后端未配置 `API_TOKEN`。
- 课表 `/api/courses`、日程 `/api/tasks`；字段以 `backend/app/schemas.py` 为准。
- 课表 `weeks` 在后端是 JSON 字符串（如 `"[1,2,3]"`），提交时传数字数组，展示由页面解析。

## 提醒（C3 简化版）

- 入口：日程页带提醒时间的任务显示「开启提醒」按钮；点击即为该任务创建/更新 phone 提醒（服务端为准，幂等：重复点击不重复创建，提醒时间变更时自动更新）。
- 到期提醒：后端调度器到期广播 reminder.due，小程序收到后在今日页「今日提醒」区展示并弹出提示；无需微信授权弹窗（2026-10-17 用户指示简化）。
- 微信离线推送仍由后端 B3 支持（docs/b3-wechat.md），本端不再走授权流程；需要时由用户在后端配置微信渠道。
- 验收：开启提醒 → 到期时小程序内出现提醒（今日页 + 提示）；逻辑 4 项 + 契约 2 项测试见 tests/。

## 接口约定

- 所有请求带 `X-API-Key` 头，由后端校验；401 = Key 无效，503 = 后端未配置 `API_TOKEN`。
- 课表 `/api/courses`、日程 `/api/tasks`；字段以 `backend/app/schemas.py` 为准。
- 课表 `weeks` 在后端是 JSON 字符串（如 `"[1,2,3]"`），提交时传数字数组，展示由页面解析。

## 订阅提醒（C3）

- 入口：日程页带提醒时间的任务显示「订阅提醒」按钮；由用户**主动点击**触发微信一次性订阅授权，页面加载不会自动弹窗。
- 流程（见 `utils/subscribe.js`）：`wx.login` → `POST /api/wechat/login`（会话存本地，60s 提前过期）→ 按任务查找/创建 phone 提醒（`POST /api/reminders`，服务端为准避免重复）→ `wx.requestSubscribeMessage` → `POST /api/wechat/subscribe`（Bearer 会话头）。
- 结果语义：同意 = 登记意图（平台最终判定），拒绝/封禁/过滤 = 登记 rejected 且**不显示订阅成功**；用户关闭弹窗 = 静默不落库；登记网络失败用**同一 request_id 重试一次**（B3 契约幂等）。
- 重复订阅：同一任务订阅成功后不再重复弹授权框、不再重复登记（本地状态提示，服务端为准）；服务端 409 视为「已订阅过」的友好提示。
- 拒绝恢复：如曾勾选「总是保持以上选择」，可在微信「我-设置-个人信息与权限-授权管理」中恢复后重试。
- 契约：`docs/b3-wechat.md`（B3）；一次性订阅不承诺「点一次必收一条」，后续订阅由用户再次主动触发。
- 前置阻塞（未配置时的行为）：`config.js` 缺 `subscribeTemplateId` → 点击提示未配置；后端未启用微信渠道 → 503 中文提示；真机链路需 B3 合并 + 模板申请 + `backend/.env` 的 WX_* 配置。
- 验收：正常授权/拒绝/取消/失败四种路径的客户端逻辑测试见 `tests/subscribe-logic.test.js`（7 项，`node tests/subscribe-logic.test.js` 运行）；真机实收见 Issue #11。
