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

日程页设置提醒时间后，主动点击“订阅提醒”。按钮处理中不可重复触发。微信授权在点击同步调用链发起；随后获取后端会话、原子创建或复用本人的 phone 提醒，查询当前事件，再登记选择。页面加载不会弹出授权窗口。

- 配置 `subscribeTemplateId`，后端启用 WX_*；AppID、模板和开发版/体验版/正式版需一致。缺配置、取消、拒绝及调用失败分别反馈。
- 同意仅表示用户选择；pending 为已登记，sent 为平台受理，手机实收另验。拒绝仍能使用课表/日程，可再次主动同意；微信记住拒绝时需在微信订阅设置中调整。
- 页面恢复、WS 重连、下拉刷新时读取本人当前事件状态。旧本地 done 标记不参与完成判断。phone 走微信渠道，不产生 `reminder.due`；应用内不会保证 phone 到期弹窗。pc/both 的既有 WS 行为不变。
- 网络结果不明时保留用户、环境、任务、事件和原 request_id；再次点击先查询原记录，未登记才重放相同请求，不自动再次授权。跨页面重进可恢复；清空应用存储后无法恢复尚未登记的选择，需要主动重新授权。服务端已登记的事件仍会去重。
- 同一任务同一用户通过新接口创建的提醒在事务中复用，包括创建成功但响应丢失。历史重复提醒返回明确冲突，需核查处理，不自动删旧数据。
- 同一绝对时刻的不同字符串不会重置事件。改期、清除提醒时间、删除日程与旧提醒失效在同一数据库事务执行；改期后需主动订阅新事件。已经发往微信的请求不能撤回。
- 消息进入 `pages/reminder/reminder`，参数只有 reminder_id；页面验证会话并读取最新内容，资源删除或其他账号无法访问时明确提示。回到已打开的页面也重新读取。
- `reminderOffsetMinutes` 默认 480，与后端 `REMINDER_NAIVE_OFFSET_MINUTES` 对齐；新时间携带偏移，展示和今天筛选按该时区。请求超时由 `requestTimeoutMs` 配置。
- 新客户端必须与本次后端协作代码一起部署。接口说明见 [C3 契约与验收](../docs/c3-subscription.md)。

## 自动化验证

需要 Node 22+ 与安装了 backend/requirements-dev.txt 的 Python 环境。在仓库根目录执行：

```powershell
npm ci --prefix miniprogram
npm run lint --prefix miniprogram
npm run format:check --prefix miniprogram
npm test --prefix miniprogram
python -m pytest -c backend/pytest.ini backend/tests -q
python scripts/check_c3_integration.py
```

Node 不在 PATH 时可设置 NODE_BINARY。逻辑回归和真实 HTTP 联调分别执行；后者使用真实页面逻辑、FastAPI、SQLite、会话和调度器，仅外部微信使用 MockTransport，数据库及凭据临时生成并清理，不覆盖 config.js。

工作流新增 miniprogram-c3 检查；本地通过不能代表远端 CI 已运行。真实设备上的弹窗、离线实收及原生消息点击需要另行记录，见 [验收记录](../docs/c3-subscription.md)。原测试中“任意 409 等于成功”和“本地 done 后永不访问服务端”的断言已改为状态校验与异常恢复断言。
