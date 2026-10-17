# B3 测试与量化报告

日期：2026-10-14；关联 [Issue #7](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/7)。起始版本 `ee1a638`，分支 `feat/backend-realtime`。本报告覆盖本次 B3 变更；后续仅文档与提交检查更新不会改变以下测试结果。

交付前同步 develop 至 `42a95ba`，保留队友小程序刷新、文档和 CI 改进；CI 同一区域冲突按两方目的合并，保留覆盖率、依赖审计与 B3 Mock 步骤。最终 B3 功能提交 `5ccfe11`；与上述测试时的后端、桌面 Python 业务源码及测试完全一致。

## 环境与复现

Windows 11 Home China 64 位，10.0.26200；Intel Core i7-1165G7，8 逻辑处理器，约 15.73 GiB RAM。后端 CPython 3.13.0 与独立 3.10.22；pytest 9.1.1、Ruff 0.17.0。依赖使用 `backend/requirements.txt` 与 `backend/requirements-dev.txt`，B3 未新增运行依赖。详情及已有环境基线见 [environment](environment.md)。

自动化使用临时 SQLite；微信请求全部由 httpx.MockTransport 接管，无真实账号、外部消息或用户数据库操作。WebSocket 回归使用本机 Uvicorn 单 worker 和真实 HTTP Upgrade，随机端口；不测手机展示和公网网络延迟。

激活对应环境，在仓库根目录运行：

```powershell
python -m pytest -c backend/pytest.ini backend/tests -q --cov=app --cov-report=term
python scripts/smoke_backend_wechat.py --samples 30
python scripts/smoke_backend_ws.py
python scripts/smoke_backend_scheduler.py --interval 1 --samples 30 --max-delay 5
python -m ruff check .
python -m ruff format --check .
python -m pre_commit run --all-files
python -m pip_audit -r backend/requirements.txt
```

桌面测试在根目录桌面虚拟环境运行 `python -m pytest tests/ -q`，测试环境 `QT_QPA_PLATFORM=offscreen`。

## 已执行结果

| 检查 | 实测结果 | 证据 |
|---|---|---|
| 后端 Python 3.13 | 168 passed，25.07 秒 | [原始输出](evidence/b3/backend-py313.txt) |
| 后端 Python 3.10 | 168 passed，22.50 秒 | [原始输出](evidence/b3/backend-py310.txt) |
| 桌面回归 | 106 项全部通过 | [原始输出](evidence/b3/desktop.txt) |
| 后端全量行覆盖 | 1086 / 1153，94.19% | [覆盖摘要](evidence/b3/coverage-summary.json) |
| 微信路由、适配器、调度、存储 | 四个新模块行覆盖均为 100%；未测分支覆盖率 | 同上 |
| 微信重复登记与发送 | 30/30 平台模拟接受，重放 30 次，重复发送 0 | [Mock 数据](evidence/b3/mock-smoke.json) |
| token 缓存 | 30 次发送只获取 1 次 token | 同上 |
| 真实 WS 广播 | 两客户端各 30 条，30 个事件 ID 一致；两次非法握手均 403 | [输出](evidence/b3/ws-smoke.json) |
| 真实 WS 到期调度 | 30/30 接收，0 超时、0 重复；p95 369.098 毫秒，最大 369.583 毫秒 | [逐条数据](evidence/b3/ws-scheduler.json) |

WS 延迟口径为计划到期 UTC 时间至本机客户端收包，扫描间隔 1 秒；不等同于 GUI 展示或微信到达。两版后端均有一条上游 Starlette TestClient 弃用提示，不影响通过；本次没有为消除提示升级已锁定的依赖。

本地提交检查：Ruff 检查、格式检查、暂存区空白检查和密钥扫描全部通过；最初发现新增文档末尾多余空行，修正后复验通过，没有绕过钩子。`pip-audit -r backend/requirements.txt` 返回 `No known vulnerabilities found`。远端 CI 以关联 PR 的实际检查记录为准。

远端复验记录：[运行 38559594613](https://github.com/Yunkimo/Intelligent-Desktop-Pet/actions/runs/38559594613) 的桌面任务通过，后端 3.12 在密钥扫描失败，3.10 因矩阵失败联动被取消。核对定位后，命中的是测试与 Mock 脚本中的两处假 WX_SECRET，未涉及真实凭证。仅在这两行增加带原因的 `pragma: allowlist secret` 注释；没有排除文件或停用扫描，业务逻辑不变。提交 b104123 的 [运行 38559975211](https://github.com/Yunkimo/Intelligent-Desktop-Pet/actions/runs/38559975211) 三组检查全部通过。

### 邮件失败记录复核与测试稳定性修正

用户提供两封失败邮件后，逐次复核发现更早的 [运行 38559431450](https://github.com/Yunkimo/Intelligent-Desktop-Pet/actions/runs/38559431450) 还存在一项此前未分析的失败：Python 3.10 中 `test_locked_database_does_not_block_event_loop_and_recovers` 的观察代码读取数据库时遇到 `database is locked`。这与上述 Mock 密钥误报是两类问题，不能用后来一次全绿推断锁竞争问题已经修复。

旧用例将数据库等待缩短为 50 毫秒，放锁后又在事件循环中反复同步 SELECT，与后台恢复事务争锁。改为通过事件观察真实的锁失败和真实的事务提交，在事务完成并停止扫描后才核对持久状态；持锁期间直接通过持锁连接验证 done=0。保留故障注入、两秒恢复期限和实际 SQLite 操作，没有跳过用例、捕获后忽略断言或改动生产逻辑。

修正后本地 Python 3.13 全量 168 项通过（15.39 秒）。针对该竞争用例的 Python 3.10 独立进程重复结果见 [重复验证数据](evidence/b3/lock-test-repeat.json)；后续 CI 以 PR #29 最新提交检查为准。

## 用例与安全设计证据

B3 新增 59 项，原有 109 项均保留。实现与用例见 `backend/tests/test_wechat.py`。

| 用例组 | 关键断言 |
|---|---|
| 身份与权限 | 同 openid 复用 ID；会话只保存摘要；再次登录撤销旧会话；过期/跨 AppID 无效 |
| 订阅归属 | 无 API Key/会话拒绝；伪造 openid 字段拒绝；他人提醒不可订阅或读取 |
| 输入与配置 | 非 UUID、模板不匹配、缺配置、额外字段、无效收件人拒绝；关闭微信不影响旧路径 |
| 幂等与授权 | 相同登记重放不增加发送；冲突 409；拒绝不发；重新同意须新登记 |
| token | 缓存、提前过期、10 个并发调用只刷新一次；无效生命周期拒绝；失效 token 只重试一次 |
| 上游异常 | 错误 code、非法 JSON/结构、HTTP 错误、43101/40037/47003 等分类，错误正文不泄露凭证 |
| 持久化发送 | 到期边界；4 个并发调度只发送一次；可恢复失败重试到上限后停止 |
| 崩溃与取消 | 发送超时、任务取消、过期租约均 uncertain；平台接受但写库失败后不会再次发送 |
| 渠道解耦 | 桌面离线仍可微信发送；both 状态独立；微信阻塞期间桌面仍继续扫描 |
| 迁移与变更 | 幂等迁移保留 B2 事件；编辑/取消使旧授权失效；发送前复核；删除级联清理 |
| 日志 | httpx URL 查询中的 code、secret、access_token 脱敏；不输出 session_key |

## 设计与重构收益口径

基线 `ee1a638` 没有 B3，不存在可比较的“旧微信发送耗时”。因此只申报新增能力及以下可复现指标，不虚构性能提升百分比。

- 适配器与依赖注入：新增 59 项用例都不需要真实微信服务；覆盖 token、网络及持久化故障。运行依赖增量为 0。
- 缓存：30 次消息复用一次 token，相对“每条发送前取一次”的理论参照少 29 次、96.67%；该参照是计算值，不是旧版本实测。
- 幂等：30 次重复登记带来的额外发送为 0；四个并发领取也只有一次实际模拟发送。
- 渠道隔离：开发自查发现单循环先后调用两渠道会拖延下一轮桌面扫描，改为两个独立循环。回归用例将微信阻塞，断言此时新桌面提醒仍能在两秒测试期限内发出。未记录改前吞吐或时延，不给出未经测量的加速比。

## 尚待验收

真实微信账号资格、模板兼容、用户授权次数、手机接收、C3 小程序联调、部署环境复现和演示视频未完成。成员独立评审与 PR 合并仍需团队执行；本地测试或 AI 自查不代替人工验收。共享 API Key 的权限边界及 uncertain 人工处理见 [接口与部署说明](b3-wechat.md)。
