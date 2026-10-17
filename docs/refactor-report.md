# 重构效果量化分析（评分点 12）

> 本报告对应考核项「重构效果增益量化」。所有数字来自 git 历史或本地实测，可复现；无法精确还原的「前值」如实标注，不编造收益。

## 1. 重构目标

桌宠端与后端在迭代中累积了多处「内联逻辑 + 硬编码 + 耦合」的结构性问题：

- 右键菜单动作内联在 `pet/window.py` 的 `contextMenuEvent` 里（`addAction` + lambda 派发），菜单构建与窗口逻辑耦合，后续托盘入口无法复用。
- 模型、形象、异步任务、配置各自耦合，切换模型/形象/参数需改多处硬编码。
- 后端外呼逻辑（微信、天气/搜索）与路由耦合，难以 mock 隔离真实外部服务。
- 气泡折行与屏幕摆位混在 GUI 类里，无法脱离 Qt 做单元测试。

## 2. 采用的设计模式（附证据）

| 模式 | 位置 | 说明 |
|---|---|---|
| 策略 + 工厂 | `pet/providers.py:1`、`pet/avatar.py:1` | `ChatProvider`/`Avatar` 抽象基类 + 各自工厂，切换模型/形象不改调用方 |
| 命令模式 | `pet/commands.py` | `Command` dataclass + `populate_menu` + `UndoStack`，菜单/托盘共用同一批命令并支持撤销 |
| 适配器 + 构造注入 | `backend/app/wechat_client.py`、`web_query.py`、`push_service.py` | 经构造注入 `transport`/`clock`，隔离真实微信与上游，便于 mock 测试 |
| 依赖注入组装 | `backend/app/main.py:20-41` | `WeChatClient → PushService → WeChatDispatcher → Scheduler` 链式装配，挂到 `app.state` |
| 纯函数抽取 | `pet/bubble.py` 的 `wrap_text`/`bubble_placement` | 折行与摆位拆成无 Qt 依赖的纯函数，可独立单测 |

## 3. 可量化的重构收益（git 可精确还原）

| 重构 | 提交 | 前后变化 |
|---|---|---|
| 右键菜单命令化 | `96ee58c` | `window.py` 571→585（+59/−45），菜单逻辑迁出为独立 `commands.py` 54 行；新增 `tests/test_commands.py` 109 行（8 例） |
| 移除 Live2D 引擎 | `3a25324` | 净 −1902 行；`avatar.py` 135→63（双策略收敛为单策略）；删除 PyQt6-WebEngine 及 Live2D 素材依赖 |
| LLM 参数配置化 | `88fefac` | `providers.py` 硬编码 `temperature`/`max_tokens` 改为 `Settings` 注入（+16/−5） |

## 4. 测试保护

- 测试文件 25 个、测试函数 230 个（桌宠 105 + 后端 125，`def test_` 口径）。
- pytest 参数化展开后：当前 develop 为后端 243 项、桌宠 116 项；B3/B4 阶段分别为后端 168/184 项、桌宠 106 项（各轮实测记录见 `docs/evidence/`）。
- 行覆盖率：B3 阶段 94.19%、B4 阶段 93.86%（见 `docs/evidence/*/coverage-summary.json`）。

## 5. 边界与诚实声明

A0 策略模式、双源配置（`.env` + `config.json`）、后端三大适配器均以**已重构形态**在基线 `b109984` 或各自首个 feat 提交进入 git，仓库历史中不存在其「内联/耦合」的前版本，因此这些部分的前后行数/耦合度无法精确还原。第 3 节的量化对照仅来自 git 历史可精确比对的三次重构；其余重构收益以第 2 节的结构证据 + 第 4 节的测试保护呈现，不虚构改前性能。
