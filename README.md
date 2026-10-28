# 智能桌宠 · Intelligent Desk Pet

[![CI](https://github.com/Yunkimo/Intelligent-Desktop-Pet/actions/workflows/ci.yml/badge.svg)](https://github.com/Yunkimo/Intelligent-Desktop-Pet/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

期末课设：三端协作的智能桌面宠物。桌宠端用文字 / 语音与用户对话，靠大模型 + 工具调用查课表、排日程、设提醒；后端是唯一数据源与调度中枢；小程序让用户在手机上查改并接收离线提醒。

## 功能特性

- **AI 学习生活规划**：文字 / 语音对话，大模型 + 工具调用自动查课表、排日程、设提醒。
- **课表提醒**：课表增删改查（桌宠端与小程序，支持拍照识别导入），到期自动提醒。
- **健康关怀**：久坐检测，按连续在座时长提醒起身喝水 / 休息。
- **多端提醒**：后端统一调度，到点经 WebSocket 推送到桌宠、经订阅消息推送到手机。
- **可联网查询**：天气、搜索等联网问答（免 key）。
- **Agent 状态监控**：Claude Code / Codex 回合状态用独立角标提示，进入「等你确认」「本轮完成」时播放提示音；角标可拖拽、双击复位，右键直接调监控开关。
- **Token 用量自查**：桌宠右下角的米饭图标点开即看今日 / 近 7 天 / 总计 token 与估算费用，并可查询 DeepSeek 账户余额。

## 系统架构

```
桌宠端（A）   ↔   后端（B）   ↔   小程序（C）
PyQt6 + Agent     FastAPI + SQLite     微信小程序
HTTP REST + WebSocket                  HTTP REST + WebSocket
                          后端 → 微信订阅消息（离线推送）
```

## 当前进度

| 部分 | 状态 |
|---|---|
| **桌宠端 A1–A4**：后端客户端 / Agent 工具调用 / 健康关怀 / 实时接收 | ✅ 已完成 |
| **桌宠端 A5–A12**：右键菜单命令化、系统托盘与开机自启、移除 Live2D、气泡自适应、Claude/Codex 状态监控、角标独立显隐与拖拽右键、状态音效、Token 用量与账户余额 | ✅ 已完成 |
| **后端 B1–B2**：WebSocket 广播 / 到期提醒调度器 | ✅ 已完成 |
| **后端 B3**：微信登录、订阅登记与离线推送 | 已实现，Mock 验证完成；实际订阅送达按 C3 专项验收 |
| **小程序 C1–C2**：骨架、课表/日程读写、识别导入与实时刷新 | 已实现；IP 开发调试路线下手机读写与断网恢复已有复验记录 |
| **小程序 C3**：订阅授权与恢复处理 | 已同步 develop 的实现及回归；微信运行时验收见 C3 专项记录 |
| **小程序 C4**：部署与运维复验 | 已完成本轮约定的 IP 调试部署与复验；另一成员独立复现由用户确认通过，正式 HTTPS/WSS 不纳入本轮验收，见 [复验报告](docs/c4-verification.md) |
| **小程序 C5**：阶段文档、CI 维护、依赖与安全说明 | 本分支同步文档并补文档/部署 CI 与结果归档，见 [C5记录](docs/c5-verification.md) |
| **工程基建**：CI 多 job、ruff、分支保护 | 保留现有检查；小程序同时运行 C3 订阅和 WS 逻辑回归 |

> B4 已按用户要求实施为后端天气 / 搜索接口（Issue #8），真实 curl 验收通过，待评审；桌宠原有本地工具继续可用，接入方式由 A/B 评审确认。

细化到验收标准的任务清单见 [docs/tasks/](docs/tasks/)。

## 快速开始

### 桌宠端（Windows PowerShell）

在仓库根目录执行；`.env` 已存在时保留原配置。

```powershell
.\setup.bat
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在本机编辑 `.env`，填写自己的 `LLM_API_KEY`、服务商 `LLM_BASE_URL` 和可用 `LLM_MODEL`；DeepSeek 示例为 `deepseek-flash`。运行：

```powershell
.\.venv\Scripts\python.exe main.py
```

也可双击 `启动桌宠.bat`。米饭图标 → “配置 API”可以保存 Key/地址并重建对话客户端；模型名仍通过 `.env` 的 `LLM_MODEL` 设置。Key 不用发给他人。首次语音识别会按配置下载模型，首次 TTS 需要外网；见 [模型与服务边界](THIRD_PARTY_NOTICES.md)。

### 后端（Windows PowerShell）

```powershell
python -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
if (-not (Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
```

在本机编辑 `backend/.env`，将 `API_TOKEN` 改成自己的随机凭据，然后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run-backend.ps1 -Port 8001 -Interval 1
```

该启动器默认仅监听 `127.0.0.1:8001`，固定单worker、不热重载。健康检查为 `GET /api/health`；业务REST需要 `X-API-Key`。桌宠 `.env` 的 `BACKEND_URL` 和 `API_TOKEN` 需与此后端一致。Linux、服务器和已有数据的操作见[部署手册](docs/deploy.md)，不要在已有线上部署运行首次安装脚本。

### 小程序

微信开发者工具导入 `miniprogram/`，核对自己的 AppID；仅首次复制 `config.example.js` 为被 Git 忽略的 `config.js`。`baseUrl`、`apiKey` 分别填写选定后端入口及对应 `API_TOKEN`，REST/上传/WS 共用该配置。

当前 C4 实际验证路线是公网 IP + HTTP/WS + 开发调试豁免，详见 [IP联调步骤](docs/C4-IP调试复验.md)。手机使用能访问该入口的网络；若安全组只放行特定公网 IP，换网络后需重新核对来源规则。连接超时先查端口与网络，401 再查凭据。C2 刷新与离线恢复已有人工作业记录；C3 微信登录/订阅的 Mock、平台受理和真机实收分别记账，见 [C3专项记录](docs/c3-subscription.md)。本轮 IP 路线不代表正式域名/证书验收或正式发布通过。

## 使用说明

- **拖拽**移动宠物，**点击**唤出 / 收起输入框，回车发送，宠物流式回复并语音播报
- **说话**：点输入框右侧 🎤 录音；或全局按住 `Ctrl+T` 录音、松开自动识别发送（右键可改快捷键）
- **右键菜单**：隐藏至托盘 / 切换图片 / 切换人设 / 设置语音快捷键 / 语音输出（勾选控制是否朗读回复）/ 监控 Claude / 监控 Codex / 显示状态角标 / 测试后端连接 / 退出
- **查看用量**：点桌宠右下角的米饭图标（跟着桌宠一起移动），查看本地 token 记账、估算费用与账户余额
- **状态角标**：Claude / Codex 角标可拖拽、双击复位；右键弹出「监控 Claude / 监控 Codex / 显示状态角标 / 查看余额 / 退出」；进入「等你确认」「本轮完成」会播放提示音
- **系统托盘**：左键点击托盘图标显示 / 隐藏桌宠；角标独立显隐，不随桌宠隐藏。右键菜单复用上述命令，可勾选「开机自启动」，「退出」固定在菜单最下方

完整操作与配置项见 [用户手册](docs/user-manual.md)。

## 目录结构

```
pet/             桌宠端（PyQt6：窗口 / 形象 / 对话 / 语音 / 记忆）
backend/         后端（FastAPI + SQLite，唯一数据源）
miniprogram/     小程序（业务页面、REST/上传、实时更新与订阅恢复）
assets/          桌宠素材（图片 / 动图）
docs/            设计文档、用户手册、测试与安全文档、三份任务书
tests/           桌宠端测试（后端测试在 backend/tests/）
scripts/         启动、备份、自检、文档检查与隔离回归
config.json      桌宠非敏感配置
.env             密钥（不提交）；后端另有 backend/.env
```

## 分工与协作

| 成员 | 负责 | 主要交付分支 | 任务书 |
|---|---|---|---|
| A [@Yunkimo](https://github.com/Yunkimo) | 桌宠端智能体 | `feat/desktop-agent`（已并入 develop） | [A](docs/tasks/A-desktop-agent.md) |
| B [@wwweiliang](https://github.com/wwweiliang) | 后端服务 | `feat/backend-realtime`（已并入 develop） | [B](docs/tasks/B-backend-service.md) |
| C [@YingboQi](https://github.com/YingboQi) | 小程序 + 部署 + 文档 | `feat/miniprogram`（已并入 develop） | [C](docs/tasks/C-miniprogram-deploy.md) |

分支模型：`main`（主干）/ `develop`（开发）/ `feat/*`（特性）。`main` 已开启分支保护（PR + CI 通过 + 1 人审批），`develop` 为开放开发分支。

## 文档

| 文档 | 说明 |
|---|---|
| [设计文档](docs/design.md) | 架构演进、分层与设计模式 |
| [重构效果量化分析](docs/refactor-report.md) | 设计模式证据、git 可还原的前后对照与边界声明 |
| [用户手册](docs/user-manual.md) | 安装、运行与操作说明 |
| [CI检查与本地复现](docs/ci.md) | 触发条件、复用任务、结果归档和限制 |
| [C5交付记录](docs/c5-verification.md) | 文档/CI/依赖说明的范围、结果与待核验项 |
| [测试文档](docs/testing.md) | 测试策略、用例清单、实验环境、覆盖率与分阶段实测 |
| [信息安全设计](docs/security.md) | 密钥管理、隐私保护、供应链 |
| [API 契约](docs/api-contract.md) | REST / WebSocket / 微信 / 天气搜索的字段与错误语义 |
| [考核证据索引](docs/assessment-evidence.md) | 各评分点对应的代码 / 测试 / 证据 |
| [第三方依赖说明](THIRD_PARTY_NOTICES.md) | 依赖许可证清单 |
| [贡献指南](CONTRIBUTING.md) | 分支、提交与代码风格约定 |
| [任务书 A / B / C](docs/tasks/) | 三人任务分解与验收标准 |

> **演示视频**：待录制后补链接（由成员 A 录制，覆盖「对话 → 排日程 → 到期提醒 → 手机收消息」端到端流程）。

## 许可证与依赖

本仓库自有代码声明为 **MIT License**（见 [LICENSE](LICENSE)）。第三方库、Qt组件、模型和素材分别适用其许可；PyQt6有GPLv3/商业许可，不能将项目MIT声明当作整套分发物的许可结论。已知待核验项及来源见[第三方说明](THIRD_PARTY_NOTICES.md)。主要依赖：

| 依赖 | 许可证 | 用途 |
|---|---|---|
| PyQt6 | GPL-3.0 / 商业 | GUI |
| fastapi / uvicorn / pydantic | MIT / BSD / MIT | 后端服务 |
| openai | Apache-2.0 | LLM 调用 |
| edge-tts | LGPL-3.0 | 语音合成 |
| faster-whisper | MIT | 语音识别 |
| sounddevice / numpy / Pillow / python-dotenv | MIT / 复合BSD许可 / MIT-CMU / BSD | 录音、数值、图像、配置 |

## 常见问题

- **听不到 / 说不了话**：确认麦克风权限已允许，且首次已下载 whisper 模型。
- **LLM 报错**：检查 `.env` 的 `LLM_API_KEY` 是否正确、`LLM_BASE_URL` 是否可达。
- **后端 401 / 503**：检查 `backend/.env` 的 `API_TOKEN` 是否与请求头 `X-API-Key` 一致（未配置会返回 503）。
