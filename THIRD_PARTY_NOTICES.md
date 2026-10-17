# 第三方依赖说明

本次清单仅覆盖 B1 后端运行依赖，来源为 PyPI 发布包的 METADATA、许可证文件及项目发布信息；
版本和环境标记以 `backend/requirements.txt` 为准。桌宠素材、模型及其他模块依赖需各负责人
继续维护，不能据此认定整个项目的授权已核验。

| 依赖 | 版本 | SPDX 许可证 | 用途 |
|---|---|---|---|
| annotated-doc | 0.0.5 | MIT | FastAPI 文档元数据 |
| annotated-types | 0.8.0 | MIT | 数据约束 |
| anyio | 4.15.1 | MIT | 异步并发与线程池 |
| certifi | 2026.7.22 | MPL-2.0 | HTTPS CA 证书集 |
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
| eslint | 10.12.0（miniprogram/package-lock.json 锁定） | MIT | 小程序 JS 静态检查（CI miniprogram job） |
| prettier | 3.9.10（同上） | MIT | 代码格式化（检查命令预留） |

安装与复现：`cd miniprogram && npm ci`（Node 22）；运行依赖仅微信基础库，无第三方运行时依赖。
