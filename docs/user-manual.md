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
| 左键点击托盘图标 | 显示 / 隐藏桌宠 |
| 右键托盘图标 | 弹出与桌宠一致的命令菜单，底部可勾选「开机自启动」 |

- 回复以气泡流式显示，同时用语音播报。
- 对话历史保存在 `data/history.json`，重启后仍在。

### 监控 Claude Code 回合状态（可选）

桌宠旁边可以显示一个独立状态角标，提示当前 Claude Code 会话的进度。角标会随桌宠位置自动翻到屏幕空闲一侧，拖到屏幕角落也不会被遮挡。该功能默认关闭，右键宠物勾选「监控 Claude」开启，再勾选一次关闭。

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

桌宠默认启用系统托盘。关闭窗口或右键选择「隐藏至托盘」只会收起桌宠，进程与提醒继续运行；左键点击托盘图标可重新显示，气泡和角标会恢复隐藏前的状态。

托盘右键菜单复用桌宠的右键命令，底部「开机自启动」勾选后，会把 `启动桌宠.bat` 的绝对路径写入当前用户的注册表 Run 键（`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`），取消勾选即移除。该功能仅支持 Windows；随登录启动时会和手动双击一样出现命令行窗口。

不想使用托盘时，可在 `config.json` 设 `"tray_enabled": false`，此时关闭窗口直接退出。

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
  "tray_enabled": true,           // 系统托盘；false 时关闭窗口直接退出
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
