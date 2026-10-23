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
| **后端 B1–B2**：WebSocket 广播 / 到期提醒调度器 | ✅ 已完成 |
| **后端 B3**：微信登录、订阅登记与离线推送 | 实现及 Mock 验证完成，[PR #29](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/29) 待评审；真机待 C3 联调 |
| **小程序 C1**：骨架 + api.js（查改课表/日程、拍照识别课表、周次设置） | ✅ 已完成 |
| **小程序 C2–C3**：实时刷新 / 订阅消息授权 | ⬜ 待开发 |
| **小程序 C4–C5**：部署 / 阶段文档、CI 与依赖安全说明 | ⬜ 待开发 |
| **工程基建**：CI 双 job、ruff、`main` 分支保护 | ✅ 已完成 |

> B4 已按用户要求实施为后端天气 / 搜索接口（Issue #8），真实 curl 验收通过，待评审；桌宠原有本地工具继续可用，接入方式由 A/B 评审确认。

细化到验收标准的任务清单见 [docs/tasks/](docs/tasks/)。

## 快速开始

### 桌宠端

```bat
setup.bat                  :: 建 .venv 并安装依赖（一次性）
copy .env.example .env     :: 填入 LLM_API_KEY
启动桌宠.bat                :: 启动（缺 .venv 会自动先跑 setup.bat）
```

也可手动运行：`.venv\Scripts\python main.py`。无后端也能纯聊天。

> 首次使用语音识别会自动下载 faster-whisper 模型（约 100~500 MB）；下载慢可先 `set HF_ENDPOINT=https://hf-mirror.com`。

### 后端

```bat
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env     :: 填入 API_TOKEN
.venv\Scripts\python run.py
```

启动后监听 `0.0.0.0:8001`，健康检查 `GET /api/health`。接口调用需带请求头 `X-API-Key: <API_TOKEN>`。

### 小程序

用「微信开发者工具」导入 `miniprogram/` 目录（`project.config.json` 已填 appid）。复制 `config.example.js` 为 `config.js`，填入后端地址与 `backend/.env` 的 `API_TOKEN`；开发期在「详情 → 本地设置」勾选「不校验合法域名」即可连本地后端。实时刷新与订阅提醒尚待联调（C2/C3），详见 [任务书 C](docs/tasks/C-miniprogram-deploy.md)。

## 使用说明

- **拖拽**移动宠物，**点击**唤出 / 收起输入框，回车发送，宠物流式回复并语音播报
- **说话**：点输入框右侧 🎤 录音；或全局按住 `Ctrl+T` 录音、松开自动识别发送（右键可改快捷键）
- **右键菜单**：隐藏至托盘 / 切换图片 / 切换人设 / 设置语音快捷键 / 监控 Claude / 监控 Codex / 显示状态角标 / 测试后端连接 / 退出
- **系统托盘**：左键点击托盘图标显示 / 隐藏桌宠；角标独立显隐，不随桌宠隐藏。右键菜单复用上述命令，可勾选「开机自启动」，「退出」固定在菜单最下方

完整操作与配置项见 [用户手册](docs/user-manual.md)。

## 目录结构

```
pet/             桌宠端（PyQt6：窗口 / 形象 / 对话 / 语音 / 记忆）
backend/         后端（FastAPI + SQLite，唯一数据源）
miniprogram/     小程序（骨架 + api.js，C1）
assets/          桌宠素材（图片 / 动图）
docs/            设计文档、用户手册、测试与安全文档、三份任务书
tests/           桌宠端测试（后端测试在 backend/tests/）
scripts/         冒烟测试
config.json      桌宠非敏感配置
.env             密钥（不提交）；后端另有 backend/.env
```

## 分工与协作

| 成员 | 负责 | 工作分支 | 任务书 |
|---|---|---|---|
| A [@Yunkimo](https://github.com/Yunkimo) | 桌宠端智能体 | `feat/desktop-agent` | [A](docs/tasks/A-desktop-agent.md) |
| B [@wwweiliang](https://github.com/wwweiliang) | 后端服务 | `feat/backend-realtime` | [B](docs/tasks/B-backend-service.md) |
| C [@YingboQi](https://github.com/YingboQi) | 小程序 + 部署 + 文档 | `feat/miniprogram` | [C](docs/tasks/C-miniprogram-deploy.md) |

分支模型：`main`（主干）/ `develop`（开发）/ `feat/*`（特性）。`main` 已开启分支保护（PR + CI 通过 + 1 人审批），`develop` 为开放开发分支。

## 文档

| 文档 | 说明 |
|---|---|
| [设计文档](docs/design.md) | 架构演进、分层与设计模式 |
| [重构效果量化分析](docs/refactor-report.md) | 设计模式证据、git 可还原的前后对照与边界声明 |
| [用户手册](docs/user-manual.md) | 安装、运行与操作说明 |
| [测试文档](docs/testing.md) | 测试策略、用例清单、实验环境、覆盖率与分阶段实测 |
| [信息安全设计](docs/security.md) | 密钥管理、隐私保护、供应链 |
| [API 契约](docs/api-contract.md) | REST / WebSocket / 微信 / 天气搜索的字段与错误语义 |
| [考核证据索引](docs/assessment-evidence.md) | 各评分点对应的代码 / 测试 / 证据 |
| [第三方依赖说明](THIRD_PARTY_NOTICES.md) | 依赖许可证清单 |
| [贡献指南](CONTRIBUTING.md) | 分支、提交与代码风格约定 |
| [任务书 A / B / C](docs/tasks/) | 三人任务分解与验收标准 |

> **演示视频**：待录制后补链接（由成员 A 录制，覆盖「对话 → 排日程 → 到期提醒 → 手机收消息」端到端流程）。

## 许可证与依赖

本项目采用 **MIT License**（见 [LICENSE](LICENSE)）。主要依赖及其许可证：

| 依赖 | 许可证 | 用途 |
|---|---|---|
| PyQt6 | GPL-3.0 / 商业 | GUI |
| fastapi / uvicorn / pydantic | MIT / BSD / MIT | 后端服务 |
| openai | Apache-2.0 | LLM 调用 |
| edge-tts | LGPL-3.0 | 语音合成 |
| faster-whisper | MIT | 语音识别 |
| sounddevice / numpy / Pillow / python-dotenv | MIT / BSD / MIT / BSD | 录音、数值、图像、配置 |

## 常见问题

- **听不到 / 说不了话**：确认麦克风权限已允许，且首次已下载 whisper 模型。
- **LLM 报错**：检查 `.env` 的 `LLM_API_KEY` 是否正确、`LLM_BASE_URL` 是否可达。
- **后端 401 / 503**：检查 `backend/.env` 的 `API_TOKEN` 是否与请求头 `X-API-Key` 一致（未配置会返回 503）。
