# 更新日志

本项目遵循[语义化版本](https://semver.org/lang/zh-CN/)与 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。

## [未发布]

### 新增

- **桌宠端（成员 A）**
  - BackendClient：用 httpx 封装后端 REST（课表/日程/提醒），自动带 `X-API-Key`。
  - Agent 工具调用：大模型 function calling + 工具循环（≤3 次）+ 联网查询（天气/搜索）。
  - 健康关怀：久坐检测（按连续在座时长）+ 喝水/休息提醒。
  - 实时接收：WebSocket 监听后端广播事件。
  - 状态角标与桌宠独立显隐：隐藏桌宠不再连带隐藏角标，新增「显示状态角标」开关。
  - 状态角标自由移动：Claude/Codex 角标可拖拽到任意位置，双击复位回自动跟随。
  - Token 用量查看：桌宠右下角的米饭图标点开即看今日 / 近 7 天 / 总计 token、估算费用，并可查询 DeepSeek 账户余额；窗口下方可直接填写自己的 API Key，无需手改配置文件。
- **后端（成员 B）**
  - 鉴权 WebSocket 广播：`/ws` 端点 + `push_service.broadcast()`。
  - 到期提醒调度器：后台循环每 30s 查到期 reminder → 广播 → 标记完成。
  - 课表图片识别导入接口（视觉解析 + 批量落库）。
- **小程序（成员 C）**
  - 骨架 + `utils/api.js`：页面与 `wx.request` 对接后端（C1）。
  - 课表拍照识别导入、本周周次设置与按周次过滤显示。
- **仓库与文档**
  - 三人分工任务书、设计文档、API 契约、测试文档。
  - CI 流水线：后端 ruff/pytest/WebSocket 冒烟，桌宠 xvfb 下 pytest。

### 变更

- LLM 温度与最大 token 改为 `config.json` 可配置（`llm_temperature` / `llm_max_tokens`）。
- 健康提醒合并为单条久坐提醒，默认间隔 45 分钟。
- 支持「今天 / 明天 / 后天 时刻」自然时间规整。
- 系统托盘右键菜单的「退出」移到菜单最下方。

### 修复

- 后端返回非 JSON 响应时的健壮性处理，工具格式化与联网失败时的友好降级。
- 工具调用回传补 `type` 字段，修复 DeepSeek 422。
- 桌宠实时事件去重、离线时回退本地中文语音。
- 后端课表识别：节次映射 / 周数 / 备注防臆造。
