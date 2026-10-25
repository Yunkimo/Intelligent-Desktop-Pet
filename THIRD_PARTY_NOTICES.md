# 第三方依赖说明

本说明覆盖后端、桌宠直接依赖、已观察到的关键传递组件、小程序开发依赖、模型/服务和仓库素材。自有代码的[MIT声明](LICENSE)不替代这些第三方条款，也不构成整个分发物许可证兼容的结论。

版本来源分别为后端锁文件、桌宠2026-10-25本机发布包METADATA和npm锁文件。桌宠requirements仅设下限，不是跨机器锁定版本；许可证摘要以实际分发包内LICENSE/NOTICE为准。未知素材和打包组件列在末尾，不伪造授权。

## 后端运行依赖

沿用B1清单并与当前 `backend/requirements.txt` 对齐；平台/版本条件仍以锁文件为准。

| 依赖 | 版本 | SPDX 许可证 | 用途 |
|---|---|---|---|
| annotated-doc | 0.0.5 | MIT | FastAPI 文档元数据 |
| annotated-types | 0.8.0 | MIT | 数据约束 |
| anyio | 4.15.1 | MIT | 异步并发与线程池 |
| certifi | 2026.10.23 | MPL-2.0 | HTTPS CA 证书集 |
| click | 8.5.0 | BSD-3-Clause | 服务器命令行 |
| exceptiongroup | 1.3.1 | MIT | Python 3.10 异常组兼容 |
| fastapi | 0.143.0 | MIT | HTTP/WS 应用 |
| h11 | 0.16.0 | MIT | HTTP 协议 |
| httpcore | 1.0.9 | BSD-3-Clause | HTTP 传输 |
| httptools | 0.9.0 | MIT | HTTP 解析 |
| httpx | 0.28.1 | BSD-3-Clause | 测试与 HTTP 客户端 |
| idna | 3.20 | BSD-3-Clause | 域名编码 |
| opentelemetry-api | 1.45.1 | Apache-2.0 | FastAPI 依赖的可观测性接口 |
| pydantic | 2.14.0 | MIT | 输入与事件 schema |
| pydantic-core | 2.50.0 | MIT | schema 校验引擎 |
| python-dotenv | 1.2.4 | BSD-3-Clause | 环境配置 |
| python-multipart | 0.0.32 | Apache-2.0 | 课表图片multipart上传 |
| pyyaml | 6.0.3 | MIT | Uvicorn 配置支持 |
| starlette | 1.7.0 | BSD-3-Clause | ASGI 与 WebSocket |
| typing-extensions | 4.16.0 | PSF-2.0 | 类型兼容 |
| typing-inspection | 0.4.4 | MIT | 类型解析 |
| uvicorn | 0.54.0 | BSD-3-Clause | ASGI 服务器 |
| uvloop | 0.23.0 | MIT | 非 Windows 平台事件循环 |
| watchfiles | 1.3.0 | MIT | 开发热重载 |
| websockets | 15.0.1 / 17.2 | BSD-3-Clause | WS 协议与冒烟客户端，按 Python 版本选择 |

发布源可按 `https://pypi.org/project/<依赖>/<版本>/` 查询。分发时保留各包随附版权和许可文件；
二进制包捆绑组件的 notices 仍以发布包内文件为准，本表不替代它们。
开发检查工具及其直接版本列于 `backend/requirements-dev.txt`，不打入应用运行依赖。

2026-10-11 的 Windows/Python 3.13 后端运行依赖扫描未发现已知漏洞，见
`docs/evidence/b1/dependency-audit.json`。这不是“没有漏洞”的保证；非 Windows 条件依赖
由 Linux CI 再验。后续变更须重跑审计。

## 小程序端 JS 检查工具（开发依赖，不打入运行）

| 依赖 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| eslint | 10.13.0（miniprogram/package-lock.json 锁定） | MIT | 小程序 JS 静态检查（CI miniprogram job） |
| prettier | 3.9.10（同上） | MIT | 已接入CI的代码格式检查 |

安装与复现：`cd miniprogram && npm ci`（Node 22）；运行依赖仅微信基础库，无第三方运行时依赖。


## 桌宠直接运行依赖

下表是已安装Windows/Python 3.13环境的观察版本，不把宽松requirements冒充锁文件。原始许可字段、classifiers、来源及许可文件名见[METADATA快照](docs/evidence/c5/desktop-package-metadata.json)；包发布页可按 `https://pypi.org/project/<name>/<version>/` 复核。

| 依赖 | 观察版本 | 许可记录 | 用途 |
|---|---|---|---|
| PyQt6 | 6.11.0 | GPL-3.0-only（本机发行包）；上游另有商业许可 | GUI及多媒体绑定 |
| openai | 3.29.0 | Apache-2.0 | OpenAI兼容模型客户端 |
| httpx | 0.28.1 | BSD-3-Clause | REST与余额查询 |
| ddgs | 9.16.0 | MIT | 桌宠本地搜索工具 |
| websocket-client | 1.9.2 | Apache-2.0 | WS监听 |
| python-dotenv | 1.2.4 | BSD-3-Clause | 本机配置 |
| edge-tts | 7.2.8 | LGPLv3（发布元数据classifier） | 在线语音合成 |
| faster-whisper | 1.2.1 | MIT | 本机语音转写 |
| sounddevice | 0.5.6 | MIT | 录音 |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 音频数组；发行包包含复合许可 |
| Pillow | 12.3.0 | MIT-CMU | 图像读取/处理 |
| pynput | 1.8.2 | LGPLv3（发布元数据） | 热键与键鼠活动监听 |

[Riverbank官方说明](https://en.riverbankcomputing.com/software/pyqt)将PyQt列为GPLv3/商业双许可。当前PyPI安装包的GPL许可不能写成MIT或LGPL。是否选择商业许可、如何分发应用与相应义务需按真实分发方案核对，本项目没有商业许可证据，也不宣称GPL与项目整体分发方案已经完成兼容性审核。

### 关键传递组件与二进制

| 组件 | 观察版本 | 元数据许可 | 额外边界 |
|---|---|---|---|
| PyQt6-Qt6 | 6.11.2 | LGPL v3 | Qt模块和捆绑第三方notices须按实际发行包核对，不能只看包装元数据 |
| PyQt6-sip | 13.13.0 | BSD-2-Clause | 保留发行包许可文件 |
| ctranslate2 | 4.8.2 | MIT | 推理引擎二进制组件仍需携带各自notices |
| av | 19.0.1 | BSD-3-Clause | PyAV包装许可不等于捆绑FFmpeg全部组件许可 |
| tokenizers | 0.23.3 | Apache-2.0（classifier） | 分词器 |
| huggingface-hub | 2.2.0 | Apache-2.0 | 下载代码许可不覆盖下载的模型 |
| onnxruntime | 1.31.0 | MIT License | 随附第三方notices另行保留 |
| cffi | 2.1.1 | MIT-0 | 运行桥接 |

PortAudio、FFmpeg、系统Qt插件及其他二进制内嵌组件的完整清单需由实际打包者从最终分发物提取。该工作尚未完成，不把本节称为完整SBOM。项目没有直接使用PyAudio依赖，不为未使用的包虚列许可。

## 开发依赖与锁定边界

后端开发工具版本在 `backend/requirements-dev.txt`；pytest/pytest-cov/Ruff/pre-commit为MIT，detect-secrets和pip-audit为Apache-2.0，具体随安装发行包保留声明。桌宠开发工具仍为版本下限，CI实际解析版本由运行结果确定。

小程序直接开发依赖ESLint 10.13.0、Prettier 3.9.10均为MIT，npm锁文件中78个包条目均有license字段，完整条目见[npm许可清单](docs/evidence/c5/npm-license-inventory.json)。这是开发工具图，不打入小程序运行；不把元数据扫描当作整棵依赖图的法律兼容结论。微信基础库由微信平台提供，不作为本项目MIT代码再许可。

[后端局部METADATA](docs/evidence/c5/backend-package-metadata.json)记录本机辅助环境：其中certifi安装为2026.7.22，与仓库锁定2026.10.23不同。该快照只作许可信息来源，不是符合当前锁文件安装的证明；CI按锁文件安装和执行审计，以实际CI证据为准。

## 素材、模型及服务

| 对象 | 可确认来源 | 当前许可/状态 |
|---|---|---|
| `assets/Rice.png` | 仓库提交247aa18引入 | 上游图片来源及授权未找到，待素材提供者/成员A补充 |
| `assets/tray.webp` | 仓库提交3ff5631引入 | 同上，不能由Git提交人身份推定图片授权 |
| 未配置frames时的内置形象 | `pet/avatar.py`程序绘制 | 按仓库代码许可维护，不代表外部图片授权 |
| faster-whisper模型权重 | 按whisper_model实际下载 | 需记录具体模型ID/修订与模型卡许可；库MIT不覆盖任意模型权重 |
| DeepSeek/视觉模型/在线TTS/微信服务 | 用户选择的服务商 | 服务使用、数据处理、账户资格与计费条款独立于SDK开源许可 |

[素材约定与来源登记](assets/README.md)同步记录未知项。上述源码包/模型/在线服务条款是不同对象，本说明不宣布所有素材可商用、整体许可证兼容或全部安全验收通过。C5负责整理，模块/素材提供者提供进一步事实。
