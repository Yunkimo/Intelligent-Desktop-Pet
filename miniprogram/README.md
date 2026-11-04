# 小程序（任务书 C）

微信小程序端：手机查改课表/日程。今日页看当天课表与到期待办，课表页/日程页增删改，经 `utils/api.js` 对接后端 FastAPI（后端是唯一数据源）；`utils/ws.js` 订阅后端 WebSocket 事件实现实时刷新。

## 目录

| 路径 | 说明 |
|---|---|
| `project.config.json` | 微信开发者工具项目配置（请核对并使用你注册的小程序AppID，仓库中的值不代替账号权限） |
| `app.js` / `app.json` / `app.wxss` | 全局入口（启动 WebSocket 适配层）、页面注册与 TabBar、全局样式 |
| `pages/index` | 今日课表 / 待办（真实教学周与当天课表来自 B6 日历接口、勾选完成、下拉刷新） |
| `pages/schedule` | 课表增删改 + 图片识别导入（按星期分组，浏览其他周与「回到本周」，周次支持 `1-16` / `1,3,5` 写法） |
| `utils/course_import.js` | 图片导入纯逻辑：草稿合并/缺项判定/节次时间映射/逐条保存结果核对与失败恢复（契约见 `docs/b7-parsing.md`） |
| `pages/task` | 日程增删改（截止日期、勾选完成）+ 一句话创建（C8） |
| `pages/semester` | 学期设置（第一周的周一 + 总周数，整体保存到后端） |
| `utils/api.js` | `wx.request` / `wx.uploadFile` 封装：`baseUrl` 与 `X-API-Key` 集中配置于文件顶部 |
| `utils/ws.js` | WebSocket 事件适配层：连接/重连/节流/去重集中管理（契约见 `docs/api-contract.md`） |
| `utils/semester.js` | 学期状态适配层：学期配置读取/保存/日历查询、离线推算与缓存（契约见 `docs/b6-contract.md`） |
| `utils/weather.js` | 带伞提醒纯逻辑：城市偏好（按账号）、订阅状态文案与可订阅判定、天气卡片文案（B 契约见 weather-subscriptions.md） |
| `utils/session.js` | 统一会话：微信登录、令牌缓存、401 单次重登、退出/切换账号与业务缓存清理（契约见 `docs/b8-accounts.md`） |
| `utils/task_parse.js` | 一句话日程纯逻辑：参考时刻构造、缺项/过去标记、逐项保存核对与失败恢复（契约见 `docs/b7-parsing.md`） |
| `utils/datetime.js` | 日期换算、提醒时间偏移与学期周次纯日历推算（后端 `day_of_week` 1=周一 … 7=周日） |
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

## 自动周数与今日课表（C6）

- 首次使用引导设置学期：「学期设置」页填第一周的周一（必须是周一，如 2026-09-07）与总周数，整体保存到后端 `PUT /api/semester`；时区由后端默认 Asia/Shanghai。
- 「今日」页显示真实教学周与当天课表（来自 `GET /api/calendar`，服务端按配置时区决定「今天」）；未配置、学期未开始、学期已结束分别提示，不显示固定的第 6/7 周。
- 「课表」页顶部选择器只用于**浏览其他周**（不改学期配置、不写本地存储），出现「回到本周」按钮；重新进入页面默认回到本周。灰色为浏览周不上课，不表示数据丢失。
- 周次由学期设置与日期推算（纯日历日差整除 7 加 1，与后端同算法）；断网时用已确认的学期配置按本机日期推算并提示「离线推算」，恢复网络后自动校准。跨午夜停留也会自动重算今天。
- 实时刷新：`semester.updated`、`course.updated/deleted`、`task.updated/deleted` 已加入事件白名单，相关页面收到推送后 REST 重读；重连后同样重读快照。
- 旧 `current_week` 本地固定周缓存已废弃，不反推开学日期。契约见 [B6 契约](https://github.com/Yunkimo/Intelligent-Desktop-Pet/blob/9e0dfed/docs/b6-contract.md)（B6 后端合入前，页面按契约开发、联调使用 B 的后端分支）。

## 图片识别导入（C7）

- 「识」入口：选图 → 预览 → 压缩（质量 80 / 宽 1920，不压糊文字）→ 上传识别。上传阶段显示真实阶段与**已等待秒数**（最长 70 秒，对应 B7 服务端 60 秒预算，由 `config.parseTimeoutMs` 控制），可点「取消识别」；取消/超时/退出页面都中止请求并忽略迟到响应，不残留转圈，也**不宣称上游计算与费用已撤销**。
- 识别结果以可编辑草稿展示（时间完整的 `courses` + 需确认的 `pending_courses`），并列出后端警告；缺时间/周次/星期的条目高亮提示，**未补全前点「确认导入」会被阻止**（确认前不写数据库）。
- 图中只有节次标签（如「1-2」「第3行」）没有具体时间时，自动按标准节次时间**预填**（第1节 08:00-09:40、第2节 10:00-11:40、第3节 13:00-14:40、第4节 16:00-17:40、第5节 19:00-20:40），草稿里可见可改；点「配置节次时间」可统一调整各节次时间。预填值在确认前都会展示，不静默套用；无节次标签的条目需手填。
- 确认后走 bulk 落库并按实际返回**逐条核对**：成功/无效/明确失败/结果不明分别处理；部分失败只保留失败项供修正后重试，不整批盲重传；响应不明先按课表列表核对，无法确认的标「结果待确认」。完成后刷新课表，真实当前周不变。
- 413=图片过大、422=无可识别内容或输入无效、503=后端未配置视觉模型、504=识别超时（可重试）、429=模型服务繁忙、502=上游异常。契约见 [B7 接口说明](../docs/b7-parsing.md)。

## 一句话创建日程（C8）

- 日程页「＋」优先打开文本输入（原手动表单保留为「手动添加」与编辑回退）。输入如「明天下午三点提醒我交实验报告；下周五前交报告」后点「解析」，调用 `POST /api/tasks/parse-text`（参考时刻为本机当前时间带偏移 + Asia/Shanghai），得到可确认草稿，不落库、不触发微信授权。
- 草稿逐条可编辑/移除；日期不明、时刻不明、提醒时刻不明、已过去分别标记「待确认」；只说截止日期不会自动生成提醒；缺失与歧义不自动修正。
- 「确认保存」逐项调用 `POST /api/tasks`（后端原子创建 PC 提醒，客户端不额外建提醒），逐项核对结果：4xx 明确失败、网络失败先按列表核对不自动重放；失败/待确认项保留原文与草稿可修正重试，防连点。
- 保存后从真实后端读回，提醒的订阅状态（未订阅/待授权等）以服务端记录为准，沿用 C3 订阅流程。契约见 [B7 接口说明](../docs/b7-parsing.md)。

## 统一会话与账号隔离（C9）

- 业务请求、图片上传与 WebSocket 统一使用微信登录会话（`Authorization: Bearer <session_token>`）；首次业务请求自动 wx.login 登录，无需手动配置。API Key 仅在后端 B8 过渡期（ALLOW_LEGACY_API_KEY）映射默认演示用户，小程序业务不依赖它。
- 401 时自动清除会话、单次重登并重试一次；仍失败提示「登录失效」且不无限重试。写请求结果不明不盲目重放；退出/切换账号推进会话代数，旧账号迟到响应被丢弃。
- 课程、日程、提醒、学期按账号隔离：非本人资源返回 404，不泄露他人数据；学期离线缓存按账号分键，退出时清理。
- 「设置」页显示当前登录账号，可退出登录（撤销会话 + 清理本机缓存）；再次使用自动重新登录。
- WS 握手令牌与会话一致，断线重连重新取当前令牌；只接收本人事件。

## 带伞提示与微信订阅（天气）

- 首页「明日带伞提示」卡片：默认城市长沙，可手动切换（常用城市或任意输入，按账号保存）；显示目标日期与更新时间，雨/无降水/暂不可用三种形态，未知可手动重试。启动、回前台、切换城市与跨上海时区午夜刷新，合并重复请求，旧请求不覆盖新城市结果。
- 「订阅带伞提醒」：订阅事件在点击前于后台准备（保证点击时同步弹出微信授权）；一次性授权只针对本次事件，仅明天有降水时 21:00 发送；accept/reject/ban/filter 与调用失败分别处理，不自动反复弹窗。
- 订阅状态以服务端为准（待授权/已授权待判断/已发送/无降水/已取消/待核实等 13 态）；取消后不能撤回已出站消息；登记结果不明用同一 request_id 幂等恢复。
- 微信消息落地页 `pages/weather-detail`：按 event_id 查询本人事件详情（城市/日期/状态/发送时间），非本人 404 不泄露数据。契约见 `weather-subscriptions.md`（B 交付）。

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
python scripts/check_c6_integration.py
python scripts/check_c7_integration.py
python scripts/check_c8_integration.py
python scripts/check_c9_integration.py
python scripts/check_weather_integration.py
```

`check_c6_integration.py` 在 B6 未合入时检测到 `/api/semester` 缺失会明确 SKIP（退出 0），合入后自动执行真实联调；合入前可用 `BACKEND_DIR` 指向含 B6 的后端检出做真实联调取证（见 [C6 验收记录](../docs/evidence/c6/c6-verification.md)）。

Node 不在 PATH 时可设置 NODE_BINARY。逻辑回归和真实 HTTP 联调分别执行；后者使用真实页面逻辑、FastAPI、SQLite、会话和调度器，仅外部微信使用 MockTransport，数据库及凭据临时生成并清理，不覆盖 config.js。

工作流新增 miniprogram-c3 检查；本地通过不能代表远端 CI 已运行。真实设备上的弹窗、离线实收及原生消息点击需要另行记录，见 [验收记录](../docs/c3-subscription.md)。原测试中“任意 409 等于成功”和“本地 done 后永不访问服务端”的断言已改为状态校验与异常恢复断言。

## C5 检查与边界同步

本轮CI继续复用miniprogram-c3的lint、格式、WS/C3逻辑及真实后端恢复检查，新增输出归档。触发和本地命令见[CI说明](../docs/ci.md)。当前C4使用IP开发调试入口，正常域名/证书或微信实收不能只凭这些自动化写成通过。Key与AppSecret、session_key和服务端access_token用途不同，服务端秘密不得打包进小程序。
