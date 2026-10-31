# B6 核验与 C6 接入

2026-10-31；成员 B；Issue #34；分支 feat/backend-b6，基线 develop 9cf0645。

## 交付范围

学期设置持久化、按当地日期推算周次和当天课程、更新/删除通知、批量刷新合并。
接口见 [B6 契约](b6-contract.md)。B5 已有事务提醒逻辑不变，未修改 C 页面、B7 或 B8。
时区使用 ZoneInfo，增加锁定的 tzdata 依赖，兼容 Windows 无系统 IANA 数据的环境。

## 本地验证

- 后端 pytest：296 passed，24.46 秒；含 28 项 B6 新测试和既有 B5/C3 回归。
- `python scripts/smoke_backend_semester.py`：真实 Uvicorn HTTP/WS，两个客户端各收到相同 7 条事件；
  5 门课批量导入只发 1 条刷新信号，404/422 无事件，断线补读及真实服务重启持久化通过。
- `python scripts/check_c3_integration.py`：10 组通过；真实 JavaScript/HTTP/数据库，外部微信平台模拟。
- `python -m pytest tests_deployment -q -o addopts=''`：41 passed，102.05 秒；使用本机 Nginx/OpenSSL，包含隔离副本回滚检验。
- Ruff 检查及格式检查通过；37 份文档/285 个本地链接检查通过，提交钩子的空白与密钥扫描通过。
- B6 冒烟已加入 backend CI 工作流；本地结果不冒充 GitHub CI 或队友的真机评审。
- pytest 有一条既有 Starlette/httpx 弃用提示，不影响本轮通过。

以上使用 Windows/Python 3.13、隔离临时数据库，不访问生产服务器，无真实微信发送。
自动周数接口通过不代表小程序已经自动切周；该页面接入属于队友 C6。

## 人工/API 复验

1. 在测试后端准备鉴权，在 `/docs` 调用 `PUT /api/semester`：
   `{"start_date":"2026-09-07","total_weeks":18,"timezone":"Asia/Shanghai"}`。
2. 查询 `/api/calendar?date=2026-10-30`，应为 week=8、day_of_week=5、status=in_term。
   查询 10-25、10-26 分别是第 7、第 8 周；9-06 为 before_term，2027-01-11 为 after_term，学期外 week=null。
3. 创建两门周五课程，weeks 分别为 `[7]` 和 `[8]`；10-30 仅返回第 8 周课程。
   空 weeks 表示每周，课程返回字段沿用既有接口。
4. 两个 WS 客户端连接同一后端。修改/删除课程或日程，两端收到相同事件后 GET 列表，结果一致；
   学期设置修改收到 semester.updated。批量导入只产生一次 course.created，需重新获取完整列表。
5. 断开一个客户端，在另一端修改，再连接并 GET；应取得最新状态。重启测试后端后 GET 学期设置应保持原值。
6. 提交非周一、无效时区、超范围总周数应 422，原配置不变且没有成功通知。未配置时返回 unconfigured，不能显示默认第 6 周。

服务器升级先备份并安装锁定依赖，再重启服务。新增 semester_settings 表为幂等建表；
旧代码忽略该表，回滚时保留它。当前 scope=shared 仍是演示模型，B8 后续必须同时隔离设置和课程查询。
本轮不在生产环境执行升级，不代替 C6 手机交互核验。
