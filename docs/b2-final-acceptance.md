# B2 / A4 修复后验收（2026-10-12）

**结论：本轮授权的后端提醒、桌宠去重和语音恢复验收通过。**
本轮由用户明确授权同一执行者完成 B2 与 A4 修改，提交身份仍为 wwweiliang，
没有冒充原 A 成员或另一名人工评审。原问题及失败数据见 [首次验收](b2-acceptance.md)。

功能提交：`1ccd3a6`（去重及声音兼容）、`65759f6`（验收脚本与口径）、
`61abdf2482c37745bc44e04a5fc82f4f9ba92741`（Windows 语音兜底）。
最终 30 条气泡与故障重连语音均在 61abdf2 上执行；默认 30 秒组在 65759f6 执行，后端代码未再改变。

## 修复与口径

- PetWindow 保留最近 1024 个已处理事件 ID，LRU 淘汰，缓存跨 WS 重连复用；
  重复事件不再拉取正文、显示气泡或播报。编辑提醒产生的新 ID 正常处理。
- 校验版本、事件类型、事件 ID 和资源 ID；处理成功后记录 ID，处理抛错可以重试。
- 按用户本轮授权采用 **1 秒联调扫描、从计划到期起 5 秒内显示气泡**；
  默认 30 秒兼容配置单独报告。两端任务书、Issue、契约和 `backend/.env.integration.example` 同步。
- 原默认 Xiaoyou 声音未出现在当时服务返回的列表中，且真实请求无音频；
  默认改为实际返回音频的 Xiaoxiao，旧默认兼容迁移，其他自选声音保留。
- 在线语音还出现连接失败：加入 Windows 系统中文语音兜底，通过固定命令及 JSON 标准输入传递文本，
  不把用户文本拼入 shell。在线/本地阶段各有超时，失败清理临时文件，播放完释放来源再清理。

本轮没有更换后端数据库技术、取消失败重试、引入第三方语音付费服务或修改小程序业务。

## 实测

| 项目 | 结果 | 证据 |
|---|---|---|
| 后端回归 | 63 项通过；业务代码仍为 B2 已验证版本 | [原始报告](b2-test-report.md)、[首次复验](evidence/b2/acceptance-backend-tests.txt) |
| 桌宠完整测试 | 106 passed，3.25 秒；新增事件缓存 94%、语音模块 98% 行覆盖，二者合计 97% | [pytest](evidence/b2/final-desktop-tests.txt) |
| 30 条真实气泡 | 30 收到、30 次通知、30 次绘制、30 个 done；30/30 在 5 秒内 | [逐条 JSON](evidence/b2/final-visible-gui-30.json) |
| 气泡延迟分布 | p50 **0.740 秒**，p95 **1.294 秒**，max **1.518 秒** | 同上，nearest-rank |
| 故障 + WS 重连 | 同一 event_id 收到 2 次，通知 1 次、绘制 1 次、语音请求 1 次；抑制 1 次重复，done=1 | [恢复及语音 JSON](evidence/b2/final-reconnect-voice.json) |
| 真实语音 | 在线失败后使用系统中文声音；真实 WAV 约 5.78 秒，QMediaPlayer 进入 PlayingState 并到达 EndOfMedia，无音频错误；临时文件已删除 | 同上及 [脱敏运行日志](evidence/b2/final-voice-runtime.txt) |
| 默认 30 秒配置 | 单条 lead=60 秒，到期后 27.348 秒绘制、done=1；只满足此组 35 秒观测阈值 | [默认组 JSON](evidence/b2/final-default-gui.json) |

语音记录证明真实生成文件及播放器完成播放，不冒称另一名成员已人工听音。
日志中的 HEVC 编码器探测提示与本次 WAV 音频解码无关，原文保留，未掩盖音频错误。
气泡时间来自 Qt 绘制后回调，精度不等于显示器扫描；本机同一时钟，非跨机器测量。

## 失败历史保留

1. 首次验收的默认 30 秒轮询和重复显示问题保留在 [历史报告](b2-acceptance.md)，没有删掉或改成通过。
2. 第一次并行运行三个真实窗口，30 次通知只记录到 26 次绘制；
   [并行数据](evidence/b2/attempt-parallel-final-gui-30.json) 判失败，不拿 30 次通知代替绘制。
3. 随后一个尚未在开始阶段确认可见的单窗口组记录 29 次绘制，首条缺失；
   [该轮数据](evidence/b2/attempt-unfocused-gui-30.json) 同样不通过。重新单窗口执行并用工具核对可见桌面后，
   最终组 30/30 通过。这说明窗口遮挡/桌面状态影响视觉验收，不能只按 WS 收包宣称显示。
4. 在线语音失败记录保留在 [首次恢复语音组](evidence/b2/attempt-parallel-final-reconnect-voice.json)，
   修复后实际走 Windows 中文兜底，不把旧失败重命名为成功。
5. [首次修复 CI](https://github.com/Yunkimo/IDP/actions/runs/38222190943) 的两个后端任务成功，
   桌宠测试收集时因缺少 libpulse.so.0 失败；补上 Linux 的 libpulse0 系统依赖，保留实际窗口入口测试。
   最终远端状态以 PR checks 为准，不能把该失败的运行记录写成成功。

## 复现与边界

Windows 11、Python 3.13.0，依赖沿用 [桌宠环境清单](evidence/b2/acceptance-desktop-packages.txt)。
每轮随机端口/凭证、临时 SQLite、真实 Uvicorn / WsListener / PetWindow / SpeechBubble；
不使用个人数据，不调用聊天模型，所有测试进程退出后临时库清理。
视觉组使用普通顶层窗口和内置猫，便于工具枚举；不等同于生产置顶行为验收。

```powershell
.venv/Scripts/python scripts/acceptance_reminder_gui.py --interval 1 --lead 20 --samples 30 --spacing 2 --hold 8 --capture-window --output tmp/gui-final.json
.venv/Scripts/python scripts/acceptance_reminder_gui.py --interval 1 --lead 12 --hold 65 --voice --capture-window --fail-first-commit --reconnect --output tmp/recovery-final.json
.venv/Scripts/python scripts/acceptance_reminder_gui.py --interval 30 --lead 60 --hold 10 --max-delay 35 --output tmp/default-final.json
```

逐轮运行、保持验收窗口可见；脚本现在会对展示数量、通知次数、限时、done、重复抑制和可选语音播放做断言，失败退出非零。
启动前不要同时运行多个叠放的验收窗口；发生遮挡时保留失败结果，再在目标可见条件下复测。
不承诺窗口重启/缓存淘汰后的恰好一次、不把 SQLite 单 worker 扩展成分布式广播。
语音依赖可用音频输出与 Windows 中文声音，在线和本地均失败时仍显示气泡并报告语音错误。
微信 B3、小程序真机、独立人工评审和他人生产恢复演练不在本轮通过结论中。
