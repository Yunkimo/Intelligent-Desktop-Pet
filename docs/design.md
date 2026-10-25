# 设计文档：架构演进与设计模式

> 智能桌面宠物（Intelligent Desk Pet）。本文保留历史重构对照，当前三端、外部数据流和IP部署图见末尾“当前三端与数据流”节。

## 1. 系统概述

桌面宠物需满足以下核心需求：

1. **桌面呈现**：无边框、置顶、透明窗口，可拖拽，形象可动。
2. **文字对话**：接入 LLM，带人设与跨会话记忆，流式回复。
3. **双向语音**：语音识别（听）+ 语音合成（说）。
4. **可维护性**：配置与逻辑解耦、第三方依赖可替换、可自动化测试。

这些需求天然要求系统具备清晰的模块边界与可扩展结构——这正是本文档讨论「重构」与「设计模式」的出发点。

## 2. 架构演进：重构前后

### 2.1 重构前（初始原型）

第一版原型把所有能力塞进单个 `MainWindow`，存在明显问题：

```mermaid
classDiagram
    class MainWindow {
        +api_key = "sk-xxxx" 硬编码
        +base_url 硬编码
        +history = []
        +send_request()  阻塞网络调用
        +play_audio()
        +on_mouse() 拖拽+点击+聊天耦合
    }
    class requests
    class pyttsx3
    MainWindow ..> requests
    MainWindow ..> pyttsx3
```

**主要问题（重构动机）：**

| 问题 | 后果 |
|---|---|
| API 密钥、路径硬编码在逻辑里 | 换环境/换模型要改代码；密钥易泄漏进版本库 |
| 网络/语音/推理全在 UI 线程同步执行 | 界面卡死、无响应 |
| 所有职责耦合在一个类 | 无法单独测试；改一处牵动全局 |
| 直接依赖具体第三方库（requests/pyttsx3） | 换 provider 需改动大量业务代码 |

### 2.2 重构后（分层架构）

重构后，系统按职责划分为「配置 / 引擎（后端）/ 线程 / UI / 记忆」五层，UI 与后端彻底解耦：

```mermaid
classDiagram
    direction LR

    class Settings {
        +llm_api_key
        +llm_base_url
        +llm_model
        +pet_name
        +personality
        +tts_voice
        +whisper_model
    }

    class ChatProvider {
        <<interface>>
        +stream_chat(messages, on_chunk) str
    }
    class OpenAICompatProvider {
        -_client
        +stream_chat()
    }
    class LLMClient {
        -provider
        +chat(messages, on_chunk) str
    }
    class TTSEngine {
        +synthesize(text) path
    }
    class ASREngine {
        +transcribe(audio) str
    }
    class Memory {
        -messages
        +add_user() +add_assistant() +get_messages() +save()
    }

    class ChatWorker
    class ASRWorker
    class TTSWorker

    class PetWindow {
        -llm -asr_engine -tts_engine -memory
        +send_text() +on_mic_toggled()
    }
    class PetSprite
    class SpeechBubble
    class ChatInput

    ChatProvider <|.. OpenAICompatProvider
    LLMClient o-- ChatProvider
    PetWindow o-- LLMClient
    PetWindow o-- Memory
    PetWindow o-- TTSEngine
    PetWindow o-- ASREngine
    PetWindow *-- PetSprite
    PetWindow *-- SpeechBubble
    PetWindow *-- ChatInput
    ChatWorker ..> LLMClient
    ASRWorker ..> ASREngine
    TTSWorker ..> TTSEngine
```

### 2.3 一次对话的时序（重构后）

```mermaid
sequenceDiagram
    participant U as 用户
    participant W as PetWindow
    participant CW as ChatWorker
    participant P as ChatProvider
    participant T as TTSWorker

    U->>W: 输入文字 / 语音转写文本
    W->>CW: start(messages)
    CW->>P: stream_chat()
    loop 流式
        P-->>CW: token
        CW-->>W: chunk → 气泡逐字显示
    end
    CW-->>W: done(完整文本)
    W->>W: 写入 Memory 并持久化
    W->>T: synthesize(text)
    T-->>W: ready(mp3 路径)
    W->>W: QMediaPlayer 播放语音
```

## 3. 设计模式应用

重构过程中明确引入/识别了以下设计模式：

| 模式 | 类型 | 应用位置 | 收益 |
|---|---|---|---|
| **适配器 Adapter** | 结构型 | `LLMClient`→OpenAI SDK、`TTSEngine`→edge-tts、`ASREngine`→faster-whisper | 隔离第三方依赖，统一内部接口 |
| **策略 Strategy** | 行为型 | `ChatProvider` / `OpenAICompatProvider` | 换 DeepSeek/通义/智谱只需新增实现，不改上层 |
| **工厂方法 Factory Method** | 创建型 | `create_chat_provider(settings)` | 创建逻辑集中，调用方不关心具体类 |
| **观察者 Observer** | 行为型 | Qt 信号/槽（`chunk`/`done`/`error`） | 线程与 UI 解耦，UI 永不阻塞 |
| **外观 Facade** | 结构型 | `PetWindow` 对外暴露极简操作 | 隐藏引擎/线程/记忆的复杂性 |

### 3.1 适配器（Adapter）

`ASREngine` / `TTSEngine` / `LLMClient` 分别把 faster-whisper、edge-tts、OpenAI SDK 的原始 API 包装成统一、极简的内部接口，业务层只依赖抽象接口。好处：升级或替换底层库时，改动被限制在适配器内部。

### 3.2 策略 + 工厂方法（Strategy + Factory Method）

LLM 接入被抽象为 `ChatProvider` 接口（策略），`OpenAICompatProvider` 是当前唯一实现；`create_chat_provider()`（工厂）按 `Settings` 决定实例化哪个策略。要接入新的 LLM 服务，只需新增一个 `ChatProvider` 子类，无需改动 `LLMClient` 与 UI 代码——直接印证「可换任意国内 API」。

### 3.3 观察者（Observer）

`ChatWorker`/`ASRWorker`/`TTSWorker` 都是 `QThread`，通过 `pyqtSignal` 向主线程发事件（观察者模式）。这是「UI 永不被网络/录音/推理阻塞」的关键：耗时操作在后台线程执行，主线程只负责响应信号更新界面。

## 4. 重构效果量化

| 指标 | 重构前（原型） | 重构后 |
|---|---|---|
| 源文件数 | 1 | 14（`pet/` 包） |
| 职责划分 | 全部耦合于 MainWindow | 配置/引擎/线程/UI/记忆 五层 |
| 配置硬编码 | 是 | 否（`.env` + `config.json` 分离） |
| UI 阻塞 | 是（同步调用） | 否（QThread + 信号） |
| 可测试性 | 无单测 | 14 个自动化用例 |
| 第三方耦合 | 直接 import 散落 | 适配器/策略隔离 |
| 设计模式 | 0 | 5 种 |

**核心代码规模**（当前）：`pet/` 约 900 行、`tests/` 约 200 行；单文件最大 `window.py` 232 行，其余模块均 <120 行，符合单一职责。

## 5. 目录结构

```
pet/
├── config.py     配置（Settings，隔离 .env 与 config.json）
├── providers.py  LLM 策略 + 工厂（Adapter/Strategy/Factory）
├── llm.py        LLM 门面（Facade）
├── asr.py        语音识别引擎（Adapter）
├── tts.py        语音合成引擎（Adapter）
├── worker.py     后台线程（Observer 的信号）
├── memory.py     会话记忆（持久化）
├── persona.py    人设提示词
├── window.py     主窗口（Facade，编排一切）
├── sprite.py / bubble.py / input_box.py   UI 组件
└── app.py        应用引导
```
## B1：后端事件通知

本分支新增的通知路径如下，接口提案见 [api-contract](api-contract.md)，待 A/C 评审。

```text
POST tasks / courses
        |
        v
线程池中的 SQLite 写入 -- 提交成功 --> PushService.notify
                                          |
                                  Event schema 校验
                                          |
                                  连接快照，并发发送
                                     /          \
                              连接 A 的锁     连接 B 的锁
                              超时则清理      超时则清理
```

`/ws` 在握手前验证 token，在断线后清理连接。每个应用生命周期只有一个 PushService，
退出时停止注册并释放连接。同步 SQLite 不在新增异步路由中直接执行；事件失败不回滚提交。
本次仅新增必要的广播边界，没有引入 ORM、中间件或额外数据库表。

## 6. 小程序端架构（C1–C4）

### 6.1 适配层与页面分层

```mermaid
flowchart LR
    P1[pages/index 今日] --> A[utils/api.js REST 适配]
    P2[pages/schedule 课表] --> A
    P3[pages/task 日程] --> A
    P3 --> S[utils/subscribe.js 订阅流程]
    W[utils/ws.js 事件适配] --> P1
    W --> P2
    W --> P3
    A --> B[后端 FastAPI]
    W --> B
    S --> B
    cfg[config.js 集中配置] --> A
    cfg --> W
    cfg --> S
```

- 页面只做交互与展示；请求统一经 `utils/api.js`（`baseUrl`/`X-API-Key` 顶部集中配置），
  WebSocket 统一经 `utils/ws.js`（连接/重连/去重/节流单例），订阅流程统一经 `utils/subscribe.js`。
- 配置派生：REST `http(s)://<host>`，WS 由同一 `baseUrl` 映射为 `ws(s)://<host>/ws?token=`。

### 6.2 事件刷新时序（C2）

```mermaid
sequenceDiagram
    participant O as 其他端
    participant B as 后端
    participant W as ws.js
    participant P as 页面
    O->>B: POST /api/courses
    B->>W: course.created（信封校验 + event_id 去重 + 节流）
    W->>P: 事件分发
    P->>B: GET /api/courses（REST 重读，唯一数据源）
```

### 6.3 可选部署方案示意（不等于本轮实测）

```mermaid
flowchart LR
    D[开发者工具/真机] -->|本地路线 http/ws 局域网| B1[本机后端 :8001]
    D -->|穿透路线 https/wss 域名| T[cpolar 隧道] --> B1
    D -->|学生机路线 https/wss 备案域名| N[Nginx TLS] --> B2[systemd 后端 :8001 单 worker]
```

细节与操作见 [deploy.md](deploy.md)；单 worker/单调度实例约束来自 B1/B2/B3 契约。

## 当前三端与数据流（C5，2026-10-25）

本节对应当前源码。后文重构前后体量、用例数是历史对照；C4部署事实引用[复验报告](c4-verification.md)，不在C5重复计作新验收。

```mermaid
flowchart LR
    U[用户] --> D[PyQt6桌宠]
    U --> M[微信小程序]
    D -->|消息与选定历史| L[OpenAI兼容LLM]
    D -->|回复文本| T[在线TTS / Windows本地兜底]
    D -->|本机录音| A[faster-whisper本地转写]
    D -->|REST / WS| B[FastAPI单进程]
    M -->|REST / 上传 / WS| B
    B --> DB[(SQLite)]
    B -->|课表图片| V[视觉模型]
    B -->|code交换 / 订阅发送| W[微信服务]
    B -->|城市或关键词| Q[B4固定查询服务]
```

桌宠LLM Key在本机配置，后端视觉Key在后端配置。ASR首次下载模型需要网络；在线TTS会发送回复文本。共享API Key保护演示业务接口，微信订阅接口另用Bearer会话，当前没有全应用多用户隔离。

### 当前IP部署拓扑

```mermaid
flowchart LR
    D[桌宠] -->|HTTP / WS :8080| N[Nginx]
    M[开发工具 / 手机] -->|HTTP / WS :8080| N
    N -->|回环8001 / Upgrade| B[systemd单worker FastAPI]
    B --> DB[(私有目录SQLite)]
    B --> S[单调度实例]
    BK[备份工具] -->|快照| CP[备份 / 恢复新副本]
```

这是用户选择并由C4核验的开发调试路线，不能当作正式域名/证书或正式发布验收。TLS部署模板保留供另行选择时使用。

### 课表图片确认导入

```mermaid
sequenceDiagram
    participant U as 用户
    participant M as 小程序
    participant B as 后端
    participant V as 视觉服务
    participant DB as SQLite
    U->>M: 选择图片
    M->>B: POST parse-image
    B->>V: 图片与识别要求
    V-->>B: 候选课程
    B-->>M: 校验后列表（不落库）
    M-->>U: 核对课程
    U->>M: 确认导入
    M->>B: POST courses/bulk
    B->>DB: 事务写入有效课程
    B-->>M: created / skipped
    B-->>M: course.created事件
    M->>B: GET courses校正页面
```

REST读回是业务数据来源，WS通知携带事件ID与资源标识。小程序在重连后补拉当前状态；桌宠提醒按ID读取正文并做内存去重，不承诺跨应用重启恰好一次。C3的用户同意、后端登记、平台受理与真机收到消息分别记录，见[专项说明](c3-subscription.md)。
