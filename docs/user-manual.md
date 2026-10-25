# 用户手册

## 1. 系统要求

- Windows 10/11
- Python 3.10+（开发环境为 3.14）
- 麦克风（语音输入用）
- 可访问 DeepSeek（或其它 OpenAI 兼容 API）的网络

## 2. 安装

### 2.1 一键安装

双击 `setup.bat`，脚本会自动创建虚拟环境 `.venv`、安装依赖，并把 Claude Code 状态监控 hooks 合并写入 `.claude/settings.local.json`（本机路径，已被 git 忽略；重复运行不会重复添加）。

或手动执行：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2.2 配置密钥

```bash
copy .env.example .env
```

编辑 `.env`：

```
LLM_API_KEY=sk-你的密钥
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

> 若用通义/智谱等其它 OpenAI 兼容服务，改 `LLM_BASE_URL` 与 `LLM_MODEL` 即可。

## 3. 运行

双击 `启动桌宠.bat`，或在命令行执行：

```bash
.venv\Scripts\python main.py
```

宠物会出现在桌面右下角。

> 首次使用语音识别会自动下载 faster-whisper 模型（约 100~500 MB）。若下载缓慢，先执行 `set HF_ENDPOINT=https://hf-mirror.com` 再运行。

## 4. 使用说明

| 操作 | 效果 |
|---|---|
| 按住宠物拖动 | 移动位置 |
| 点击宠物 | 唤出 / 收起输入框 |
| 输入文字后回车 | 发送，宠物流式回复并语音播报 |
| 点输入框右侧 🎤 | 开始录音（变 ⏹）；再点停止，转写后发送 |
| 按 Esc | 收起输入框 |
| 右键宠物 | 弹出命令菜单，顶部为「隐藏至托盘」 |
| 右键勾选「显示状态角标」 | 独立控制 Claude / Codex 角标是否显示；桌宠隐藏至托盘时角标不受影响 |
| 左键点击托盘图标 | 显示 / 隐藏桌宠 |
| 右键托盘图标 | 弹出与桌宠一致的命令菜单，可勾选「开机自启动」；「退出」固定在菜单最下方 |
| 点击右下角米饭图标 | 打开「Token 用量」窗口；图标跟随桌宠移动，从图标上按下也能直接拖动桌宠 |

- 回复以气泡流式显示，同时用语音播报。
- 对话历史保存在 `data/history.json`，重启后仍在。

### 监控 Claude Code 回合状态（可选）

桌宠旁边可以显示一个独立状态角标，提示当前 Claude Code 会话的进度。角标会随桌宠位置自动翻到屏幕空闲一侧，拖到屏幕角落也不会被遮挡。该功能默认关闭，右键宠物勾选「监控 Claude」开启，再勾选一次关闭。角标是否显示另由「显示状态角标」独立控制，与监控开关互不影响。

角标可以**自由拖动**到屏幕任意位置：拖走后自动摆位不再覆盖它，双击角标即可复位回自动跟随（手动位置仅本次运行有效，不持久化）。Claude 与 Codex 两个角标都支持。

| 角标 | 含义 |
|---|---|
| Claude 处理中… | 已提交提示词，Claude 正在处理 |
| Claude 等你确认 | Claude 正在等待你确认权限 |
| Claude 本轮完成 | 当前回合的最后一条回复已输出 |
| Claude 状态未知 | 处理中/等你确认超过 5 分钟没有新事件（可能被中断或异常退出） |

状态由 Claude Code hooks 写入 `data/agent-status.json`。运行过 `setup.bat` 的话，hooks 已自动写入 `.claude/settings.local.json`，可跳过下面的手工配置；需要手动生成时执行：

```bat
.venv\Scripts\python scripts\install_claude_status_hook.py
```

脚本会保留已有配置、重复运行不重复添加，并自动使用本机 Python 与脚本的绝对路径。也可以手工编辑项目根目录的 `.claude/settings.local.json`（个人本地配置，已被 git 忽略）：

```json
{
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "\"$CLAUDE_PROJECT_DIR/.venv/Scripts/python.exe\" \"$CLAUDE_PROJECT_DIR/scripts/claude_status_hook.py\"", "timeout": 5 }] }],
    "PreToolUse":       [{ "hooks": [{ "type": "command", "command": "\"$CLAUDE_PROJECT_DIR/.venv/Scripts/python.exe\" \"$CLAUDE_PROJECT_DIR/scripts/claude_status_hook.py\"", "timeout": 5 }] }],
    "PostToolUse":      [{ "hooks": [{ "type": "command", "command": "\"$CLAUDE_PROJECT_DIR/.venv/Scripts/python.exe\" \"$CLAUDE_PROJECT_DIR/scripts/claude_status_hook.py\"", "timeout": 5 }] }],
    "Notification":     [{ "hooks": [{ "type": "command", "command": "\"$CLAUDE_PROJECT_DIR/.venv/Scripts/python.exe\" \"$CLAUDE_PROJECT_DIR/scripts/claude_status_hook.py\"", "timeout": 5 }] }],
    "Stop":             [{ "hooks": [{ "type": "command", "command": "\"$CLAUDE_PROJECT_DIR/.venv/Scripts/python.exe\" \"$CLAUDE_PROJECT_DIR/scripts/claude_status_hook.py\"", "timeout": 5 }] }],
    "SessionStart":     [{ "hooks": [{ "type": "command", "command": "\"$CLAUDE_PROJECT_DIR/.venv/Scripts/python.exe\" \"$CLAUDE_PROJECT_DIR/scripts/claude_status_hook.py\"", "timeout": 5 }] }],
    "SessionEnd":       [{ "hooks": [{ "type": "command", "command": "\"$CLAUDE_PROJECT_DIR/.venv/Scripts/python.exe\" \"$CLAUDE_PROJECT_DIR/scripts/claude_status_hook.py\"", "timeout": 5 }] }]
  }
}
```

如果当前 shell 不展开 `$CLAUDE_PROJECT_DIR`，把两处路径换成项目绝对路径（路径含空格时必须保留引号）。修改 hooks 后需重启 Claude Code（hooks 在会话启动时加载），也可用 `/hooks` 查看是否生效。

> 脚本只写入状态名、事件名、会话 ID 与时间戳，不记录对话内容；写入失败或输入非法时静默退出，不影响 Claude Code 本身。

### 系统托盘与开机自启

桌宠默认启用系统托盘。关闭窗口或右键选择「隐藏至托盘」只会收起桌宠与气泡，进程、提醒和状态角标继续运行；左键点击托盘图标可重新显示桌宠，气泡恢复隐藏前的状态。角标是否显示由「显示状态角标」独立控制，不随桌宠显隐。

托盘右键菜单复用桌宠的右键命令，勾选「开机自启动」后，会把 `启动桌宠.bat` 的绝对路径写入当前用户的注册表 Run 键（`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`），取消勾选即移除。「退出」始终排在菜单最末一项，避免与上面的勾选项混在一起、误点关闭桌宠。该功能仅支持 Windows；随登录启动时会和手动双击一样出现命令行窗口。

不想使用托盘时，可在 `config.json` 设 `"tray_enabled": false`，此时关闭窗口直接退出。

### Token 用量与账户余额

点击桌宠右下角的米饭图标打开用量窗口，分三块：

- **本地记账**：今日 / 近 7 天 / 总计的请求数、输入 token、其中缓存命中、输出 token 与估算费用。每完成一次模型调用（含工具循环里的每一轮）记一条，写入 `data/usage.json`，按天明细默认保留 90 天，总计不受裁剪影响。
- **账户余额**：点「刷新余额」联网查询，分行显示服务商、币种、总余额、余额构成（赠送 / 充值）、状态与查询时间。不可用时会标红提示充值；查询失败时保留上一次的有效数值，只更新状态行。查询在后台线程执行，不会卡住界面；DeepSeek 的余额接口在部分网络下需要约 8 秒才返回，此时保持「正在查询」即可。
  > DeepSeek 与 Moonshot 的开放接口都只提供余额查询，**没有查询历史用量的接口**，因此账户侧的「近七天用量」无法获取。需要看消耗趋势请用上方「桌宠本地用量」表格，那是本机逐次调用累加的结果。

  「刷新余额」下方的「跳转至API网站」会在系统默认浏览器打开服务商控制台的用量页（DeepSeek 默认跳到 `https://platform.deepseek.com/usage`；未收录的服务商退回 API 地址的站点根）。想指向别的页面（比如账单或密钥管理），在 `config.json` 设 `"api_website"` 即可覆盖。地址为空时按钮置灰，改完「API 地址」后提示会即时更新。
- **费用估算**：按 DeepSeek 官方价目（更新于 2026-10-24）折算人民币。空闲价为高峰价的一半，高峰是北京时间工作日 9:00-12:00 与 14:00-18:00。**法定节假日与调休没有建模**，节假日会按高峰价高估；未收录的模型只记 token 不算钱。费用仅为自查参考，不替代官方账单。

账户余额用的是独立凭据：在 `.env` 里设置 `ACCOUNT_API_KEY`（留空则回退 `LLM_API_KEY`），`ACCOUNT_BASE_URL` 留空则回退 `LLM_BASE_URL`，因此可以用 A 家的 key 推理、查 B 家账户余额。当前只支持提供官方余额接口的 DeepSeek 与 Moonshot，其余服务商如实提示「未提供余额查询接口」，本地记账照常可用。

还没有 key 的新用户不用改文件：窗口最下方有「配置 API」三栏，粘贴后点「保存」即可，**留空的栏位保持不变**。

| 栏位 | 写入 `.env` | 作用 |
|---|---|---|
| API Key | `LLM_API_KEY` | 桌宠对话接入用的 key；保存后立即重建客户端，无需重启 |
| API 地址 | `LLM_BASE_URL` | 可选；留空沿用当前地址，没写协议会自动补 `https://` |
| 账户查询 Key | `ACCOUNT_API_KEY` | 可选；留空则沿用上面的 API Key |

key 只写入本机 `.env`（已被 git 忽略，不会提交），不会进 `config.json`。输入框是密码模式，保存后立即清空，提示里只回显头尾几位，界面和截图都不留明文。改了 API Key 或地址后，账户余额会用新配置自动刷新。

### 监控 Codex 回合状态（可选）

Codex 使用与 Claude 独立的「监控 Codex」右键开关和角标。运行 `setup.bat` 会把 hooks 合并到用户级 `%USERPROFILE%\.codex\hooks.json`（若设置了 `CODEX_HOME`，则使用该目录）；也可手动运行：

```bat
.venv\Scripts\python scripts\install_codex_status_hook.py
```

在 Codex 中检查并信任这些 hooks，然后重启 Codex。hook 只把事件名、会话 ID、回合 ID 和时间写入 `data/codex-agent-status.json`，不保存提示词与工具内容。缺少配置、hook 或状态文件不会影响桌宠及 Claude 监控。`PermissionRequest` 显示等待确认，`Stop` 显示本轮完成，超过 5 分钟没有新事件时进行中状态会显示未知。

同时打开多个 Codex 会话时，角标跟随最近提交用户消息的会话；其他会话的后台事件不会抢占显示。本轮完成后，迟到的工具事件不会重新显示“处理中”，下一次提交消息才开始新的监控回合。旧客户端缺少回合 ID 时，只能依靠用户消息和结束事件区分回合，无法完整识别跨回合的乱序事件。

## 5. 自定义

所有非敏感配置在 `config.json`：

```jsonc
{
  "pet_name": "小萌",            // 宠物名字
  "persona": { "personality": "…", "tone": "…" },  // 人设
  "frames": ["idle_0.png"],       // 形象帧（见 assets/README.md）
  "sprite_size": 180,
  "tts_voice": "zh-CN-XiaoxiaoNeural", // 音色；旧默认 Xiaoyou 在加载时迁移
  "tts_rate": "+10%", "tts_pitch": "+20Hz",
  "whisper_model": "base",        // 识别精度：base/small/medium
  "enable_voice": true,           // 关闭语音播报
  "monitor_claude": false,        // Claude Code 回合状态角标（右键可切换）
  "monitor_codex": false,         // Codex 回合状态角标（右键可切换）
  "status_badges_visible": true,  // 状态角标总开关；false 时不显示角标，监控仍运行
  "tray_enabled": true,           // 系统托盘；false 时关闭窗口直接退出
  "usage_retention_days": 90,     // token 记账按天明细保留天数；总计不裁剪
  "balance_timeout_seconds": 10,  // 账户余额查询超时（秒）
  "rice_icon": "Rice.png",        // 右下角用量入口图标（相对 assets/）
  "api_website": "",              // 「跳转至API网站」目标；留空用服务商控制台用量页
  "max_history": 20               // 记忆轮数
}
```

## 6. 常见问题

| 现象 | 处理 |
|---|---|
| 启动提示未配置 LLM_API_KEY | 按 2.2 填 `.env` 后重启 |
| 语音识别没反应 | 确认麦克风权限已允许、whisper 模型已下载 |
| 回复乱码/报错 | 检查 `.env` 密钥与 base_url 是否可达 |
| 想换宠物形象 | 图片放入 `assets/` 并更新 `frames` |
| 找不到托盘图标 | 点击任务栏右下角的 `^` 展开隐藏图标，并确认 `tray_enabled` 未设为 false |
## 桌宠端 A1–A4 联调说明

对应 issue [#1](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/1)–[#4](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/4)，PR [#17](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/17)。

### 后端连接（A1）

桌宠经 `BackendClient`（httpx）访问后端 REST。先起后端并保证 `.env` 的 `BACKEND_URL`、`API_TOKEN` 与后端一致：

```bat
cd backend && .venv\Scripts\python run.py   :: 监听 8001
```

- 桌宠内「测试后端连接」应显示「后端正常，课表 N 条、日程 N 条」。
- 本地请求默认绕过系统代理（`trust_env=False`），避免被本机 Clash 等代理拦成 502。

### 工具调用（A2）

直接对话即可触发，无需额外配置：

- 「帮我加一条明天上午复习英语的日程」→ 写入后端 SQLite。
- 「查一下明天天气」→ 返回实时天气（wttr.in）。
- 工具循环最多 3 次，超出转为普通回复。

### 健康关怀 / 久坐提醒（A3）

`config.json`：

```jsonc
"health_enabled": true,        // 总开关
"sedentary_interval_min": 45   // 连续久坐满多少分钟提醒一次
```

判定：**1 分钟内无键鼠输入 = 离座（计时清零）**；否则算「在座」，连续在座满 `sedentary_interval_min` 分钟提醒一次，之后每再满一个间隔再提醒。触发时气泡 + 语音「坐太久啦，起来喝口水、活动一下吧～」。

快速验证：把 `sedentary_interval_min` 临时改成 `1`，持续动键鼠约 1 分钟即触发；验完改回 `45`。

### 实时接收（A4）

`WsListener` 维持 WebSocket 长连接（`/ws`），收到后端事件弹气泡 + 语音：

- `task.created` / `course.created`：新增日程/课表的资源 ID 通知。
- `reminder.due`：提醒到期（依赖后端 B2 到期调度器，未就绪前不触发）。

断线自动重连并重新拉取 REST 状态。

# 后端 B1 实时广播联调

本节对应 [Issue #5](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/5)，契约尚待 A/C 评审。
在 `backend/` 安装 `requirements-dev.txt`，复制 `.env.example` 为 `.env`，填入随机 `API_TOKEN`。
执行 `python run.py` 启动开发服务（监听 8001，热重载会断开连接）。

客户端连接 `ws://127.0.0.1:8001/ws?token=<URL 编码的 API_TOKEN>`。
通过 REST 创建日程或课表后，已连接客户端收到资源 ID 通知，再用 REST 读取完整状态。
完整字段及失败语义见 [API 契约](api-contract.md)。不要把密钥放进截图或命令历史。

在仓库根目录用后端虚拟环境执行 `python scripts/smoke_backend_ws.py`，脚本自行启动临时服务，
用两个真实 WebSocket 客户端检查 30 次广播、错误凭证拒绝和日志脱敏。它只写临时数据库，
会清理进程和文件，失败返回非零退出码，不影响个人数据库。

服务器部署命令（从 `backend/` 执行；由环境提供密钥，固定一个 worker）：

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1 --ws websockets-sansio --ws-max-size 4096
```

该命令不启用热重载。对外接入需由部署负责人配置 TLS、代理 query 脱敏和访问控制，
公网用户会话方案另行评审。当前不提供多用户隔离。

排查：握手 403 检查 token 和服务端配置；普通 HTTP GET 404 不表示 WS 不可用；
断线后重连并重新拉取 REST；慢客户端可能以 1013 关闭。收不到提醒到期事件时，
检查是否启用 B2、提醒 channel、到期时间及发送状态。备份与恢复使用
`scripts/backup_backend_db.py`，调度行为与故障恢复用例见 [测试文档](testing.md) §3.2；`phone` 渠道见下文 B3。

### A4 / B2 提醒联调

把 `backend/.env.integration.example` 的配置项合并到后端 `.env` 并重启服务，
联调使用 1 秒扫描；验收从计划到期计时，要求气泡在 5 秒内显示。默认 30 秒配置另行测量。
桌宠自动缓存最近 1024 个已处理事件，断线重连不会重复弹出或播报同一事件。
应用重启会清空缓存，缓存淘汰后的旧事件也可能再次显示；当前不保证跨重启恰好一次。

语音默认使用 `zh-CN-XiaoxiaoNeural`，旧默认 `zh-CN-XiaoyouNeural` 在读取时兼容迁移，
不覆盖其他自选声音。`tts_timeout_seconds` 默认 30 秒（允许大于 0、最多 120），
上游失败或超时会清理临时音频，气泡仍然显示；TTS 需要外网与可用的输出设备。
Windows 默认允许 `tts_windows_fallback=true`：在线服务失败后使用系统中文声音生成 WAV，
经同一播放器播放，无须网络；需要已安装中文语音（本机为 Microsoft Huihui Desktop）。
在线和本地阶段各受 `tts_timeout_seconds` 限制，因此故障时总等待可能达到两倍该值；
气泡显示不等待语音合成。非 Windows 系统没有此兜底，仍报告在线服务错误。

## B3 微信提醒使用入口

微信功能默认关闭，不影响桌面使用。开发验收可在后端虚拟环境运行 `python scripts/smoke_backend_wechat.py --samples 30`，不需要真实微信凭证。真实使用需要后端配置账号和模板，C3 完成登录、提醒归属绑定及用户主动授权；登录、订阅与发送状态的完整契约见 [API 契约](api-contract.md) §微信，故障与安全用例见 [测试文档](testing.md) §3.2 与 [信息安全设计](security.md)。当前真机接收和 C3 界面尚待联调。
## B4 天气与搜索入口

后端启动后，可使用带 X-API-Key 的 curl 请求获取天气和搜索摘要，输入/响应契约与错误语义见 [API 契约](api-contract.md) §天气与搜索。无需天气/搜索上游密钥；无公网条件下运行 `python scripts/smoke_backend_web_query.py` 验证 Mock 链路，显式增加 `--live` 才进行真实上游验收。

# 小程序端（C）

## 安装与配置

1. 微信开发者工具导入 `miniprogram/` 目录（appid 已在 `project.config.json`）。
2. 复制 `config.example.js` 为 `config.js`，填 `baseUrl`（本机 `http://127.0.0.1:8001`，真机用电脑局域网 IP）与 `apiKey`（= `backend/.env` 的 `API_TOKEN`）。
3. 开发期：详情 → 本地设置 → 勾选「不校验合法域名」（仅限调试；正式路线见 [部署手册](deploy.md)）。
4. 后端运行：`powershell -File scripts\run-backend.ps1`（自动建 venv/装依赖）。

## 主要操作

- **今日页**：顶部切换「第 X 周」（本地保存，两页联动）；显示今天的课与到期待办；勾选完成；下拉刷新。
- **课表页**：右下「＋」增删改课程（周次支持 `1-16`/`1,3,5` 写法）；绿色「识」按钮拍照/选图识别导入；本周不上课的课程置灰标「本周不上」。
- **日程页**：增删改与勾选完成；编辑可设提醒时间（日期+时间）；带提醒时间的任务有「订阅提醒」按钮，触发微信一次性订阅授权。

## 故障排查

| 现象 | 排查 |
|---|---|
| HTTP 401：API Key 无效 | `config.js` 的 `apiKey` 与 `backend/.env` 的 `API_TOKEN` 不一致 |
| 网络请求失败 | 后端未启动或 `baseUrl` 不对；真机需同一 WiFi 且防火墙放行 8001（见部署手册） |
| 识别返回 503 | 后端未配置视觉模型（`LLM_API_KEY`/`LLM_BASE_URL`/`LLM_VISION_MODEL`） |
| 点订阅提醒提示未配置模板 | `config.js` 的 `subscribeTemplateId` 为空（需在微信公众平台申请模板） |
| 订阅登记 503/401 | B3 后端未启用（`WX_ENABLED`）或会话过期（重新点一次会重新登录） |
| 页面不自动刷新 | 后端事件连接依赖 WS；重进页面会 REST 重读，杀后端再重启会退避重连 |
