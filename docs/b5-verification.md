# B5 后端独立交付与核验

2026-10-30；成员 B；Issue #33；分支 `feat/backend-b5`，基线 develop `0732750`。

## 范围

复用已关闭 PR #68 的后端实现，重新在最新 develop 上检验。只交付日程与提醒事务联动，不包含 B6/B7、C6 页面或 A 桌宠功能改动。小程序测试仅调整为分别核对 PC/phone 记录，保留现有 C3 功能。

沿用 SQLite、_update_reminder、seed_delivery 和现有调度器：创建任务自动安排 PC 提醒，未发送内容/时间同步，完成/清空/删除失效旧计划，独立提醒不变。过去时间允许下一扫描发送；重新打开按保留时间重新安排；等价时间/重复更新不重置事件。启动不批量补发历史日程，具体历史修复及授权规则见 [API 契约](api-contract.md)。

## 本次实际检验

Windows / Python 3.13，临时数据库，微信上游模拟，不连接生产服务或使用真实凭据。

- `python -m pytest -c backend/pytest.ini backend/tests -q`：268 passed，16.67 秒。覆盖创建/修改/完成回滚、旧领取失效、并发重放、历史数据、内容/时间和手机授权。
- `python scripts/check_c3_integration.py`：10 组通过，真实 JavaScript、HTTP、数据库和调度，微信平台/原生 wx 为模拟；不代表真机界面验收。
- `python scripts/smoke_backend_ws.py`：2 客户端各 30 事件、event_id 一致、2 次错误凭据 403、日志脱敏通过。
- `python scripts/smoke_backend_scheduler.py --interval 1 --samples 30 --max-delay 5`：30/30 接收，0 超时/重复，30 条 done；最大延迟 1013.939ms。口径为计划到期至本地 WS 接收，不是桌宠 GUI 展示。
- `python -m pip_audit -r backend/requirements.txt --progress-spinner off`：无已知漏洞（本次查询结果）。
- `python -m pytest tests_deployment -q -o addopts=''`：41 passed，107.97 秒，无跳过；使用本机 Nginx/OpenSSL，含真实历史回滚和源码不匹配拒绝。
- Ruff 全仓检查通过，177 个 Python 文件格式通过；Prettier、35 份文档/281 个本地链接以及 C4 专项链接检查通过。

## 旧 CI 失败修正

PR #68 的 deployment-docs 失败于 test_server_rollback_cli：用 origin/develop 校验功能分支源码，后端改动必然不一致。本次改为 HEAD；仍保留真实源码不匹配必须拒绝的负向测试，没有削弱生产回滚脚本的保护。

## API 人工复验步骤

1. 在隔离后端通过 POST /api/tasks 保存未来一分钟 remind_at；GET /api/reminders 应只有一条该 task_id 的 PC 关联。
2. PUT task 修改标题、备注及时间；提醒内容同步，旧时间无新发送，新时间收到一次；重复保存不换 event_id。
3. 分别完成、清空提醒、删除测试日程；旧领取不可发送/写回，新扫描不领取该提醒，独立提醒仍可领取。
4. 完成后重新打开，按保留时间安排新事件；过去时间下一扫描发送。微信需主动重新授权，已出站请求不能撤回。
5. C6 #77 独立进行页面交互与真机核验；A 协作验证桌宠展示。另一成员评审后合并，不把自动化当成员评审。

本次未更新生产部署。Issue 保持 open；新 PR 只交付 B5 后端，C6 不作为本次编码任务，也不标为已完成。
