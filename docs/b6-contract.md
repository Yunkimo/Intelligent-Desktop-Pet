# B6 学期日历接口

供 C6 接入；现阶段沿用共享演示数据和 `X-API-Key`，不是多用户隔离。
不得由客户端传入 scope/user_id 选择他人设置；B8 后续从已验证身份确定作用域。

| 请求 | 返回 / 行为 |
|---|---|
| GET /api/semester | `{configured:false, settings:null}` 或当前 settings |
| PUT /api/semester | 完整保存 `{start_date:"2026-09-07",total_weeks:18,timezone:"Asia/Shanghai"}` |
| GET /api/calendar?date=2026-10-30 | 日期、星期、周次、状态、设置及当天有效课程 |

`start_date` 必须是周一，`total_weeks` 为 1～53 的整数；时区必须是有效 IANA 名称，
省略时默认 Asia/Shanghai。未知字段、非法日期/时区或超范围返回 422；沿用 401/503 鉴权错误。
PUT 为整体替换，不支持部分更新；成功返回与 GET 相同结构。settings 包含 id=1、start_date、total_weeks、timezone。

calendar 返回 `date`（YYYY-MM-DD）、`day_of_week`（1～7）、`week`（整数或 null）、
`status`（unconfigured / before_term / in_term / after_term）、`timezone`、`settings` 和 `courses`。
省略 date 时取设置时区的服务器今天；未配置使用 Asia/Shanghai 显示日期，但 week=null、courses=[]。
学期外同样 week=null、courses=[]，不夹到第 1/最后一周。读操作不保存、不改周次。
教学周按当地日历日差整除 7 加 1；课程沿用原字段和 weeks JSON 字符串，空列表表示每周，
非空列表仅匹配指定周次（单双周由列表表达）。坏的历史 weeks 不当成每周有效。

新增 `task.updated/deleted`、`course.updated/deleted`、`semester.updated`，
均沿用 version=1 信封和 data.id，学期设置的 id 固定为 1。
完成/重开是 task.updated；B5 同事务的提醒变更由该事件提示消费者补读提醒，不重复发送业务通知。
成功更新（含相同值 PUT）可通知一次；404/422/事务失败不通知。删除事件携带被删除 ID，消费者刷新列表。
批量课程导入仍发兼容的 course.created，但每批只发一次，data.id 为本批第一条课程；
该 ID 是刷新提示，不是本批完整记录，必须 GET /api/courses 校正列表。旧客户端的列表刷新仍可工作。
推送异常不改变已经提交的 HTTP 结果；事件不持久化、不保证全局顺序。先建 WS 再读快照，重连补读 REST。

存储为独立的 semester_settings 表，scope='shared'；新增表不占用 B8 的用户迁移版本。
现有库启动时幂等建表，不改已有课程/日程。B8 接入时需迁移共享设置归属并按认证身份传递作用域。
回滚旧代码时此新增表保留但被忽略，部署前沿用既有数据库备份流程。
本项不修改小程序，不实现自动课前提醒、停调课或账号体系。
