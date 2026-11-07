# B8 账号与用户隔离契约

对应 Issue #81，后端由 B 交付；桌宠 A19 #82、小程序 C9 #83 独立接入。B8 不实现客户端登录界面，不更改服务器配置。

## 身份和兼容范围

- 通用 `users` 为业务主表；`wechat_users.business_user_id` 关联它。一个 AppID/openid 对应一个业务用户。
- 微信登录 `POST /api/wechat/login {"code":"..."}` 不再要求共享 API Key；仍由真实微信 code 交换校验。返回原有 `user_id`（微信身份 ID）、新增 `account_id`（业务用户 ID）、`session_token`、`expires_in`、openid。openid 不是凭据。
- 业务接口使用 `Authorization: Bearer <session_token 或 device_token>`。缺失、过期、撤销或错误令牌返回 401。显式错误 Bearer 不会退回 API Key。
- `ALLOW_LEGACY_API_KEY=true` 为过渡默认值：旧 `X-API-Key` 和 WS API Key 仅映射默认演示用户 `1`，只能读写其历史共享数据，不能读写微信用户数据。正式多用户部署设为 `false`。保留 `require_token` 用于服务端测试和管理通道。
- 学期配置使用 `user:<account_id>` 作用域，课程、日程、提醒均有 `user_id`；客户端提供的 `user_id` 不参与归属判定。解析接口只返回当前请求草稿，不读写其他用户数据。
- `GET/PUT/DELETE /api/{courses|tasks|reminders}/{id}` 对不存在和非本人资源均返回 404。提醒关联 task_id、wechat_user_id 也校验同一业务用户；越权关联 404。微信订阅历史仍保持 B3 的空列表语义，非本人只返回 `[]`，不泄露记录。

## 桌宠设备登录（A19）

桌宠通过 `POST /api/auth/device` 兑换配对码。响应禁止缓存，令牌只在签发时返回，数据库仅存 SHA-256 摘要。

私人账号跨端配对：已登录用户通过 Bearer 调用 `POST /api/auth/pairing`，返回 6 位数字字符串 `pairing_code` 和 `expires_in=7776000`（90 天）。桌宠发送 `{"pairing_code":"012345"}`，保留前导零。新码生成后旧码失效。兑换配对码与签发设备会话在同一事务内完成。重放、过期或错误返回 401。

同一来源在 15 分钟内 5 次失败，或服务内 24 小时内累计 20 次失败后，配对兑换返回 429 和 `Retry-After`。限流状态保存在 SQLite，已有会话可继续访问业务接口。数字码以服务端密钥计算 HMAC。签发时优先使用 `WX_SECRET`，未配置时使用 `API_TOKEN`，轮换对应密钥会使已有数字码失效。版本 6 迁移前备份数据库，旧版长码仍按原到期时间兑换。

设备登录响应：`{"user_id":2,"device_token":"签发值","token_type":"Bearer","expires_in":2592000}`。
`DEVICE_SESSION_TTL_SECONDS` 默认 30 天，可设 60～7776000 秒。设备过期重新登录/配对，不提供静默刷新。
`GET /api/auth/me` 返回业务 `user_id`。`POST /api/auth/logout` 使用当前 Bearer，204；撤销当前会话，不清空业务数据、不撤销其他设备。微信再次登录只旋转微信会话，不撤销已有设备会话。

设备令牌保存在客户端受控存储，不提交 Git、不放截图或日志。配对码也属于凭据。私人配对应经可信渠道交付，账号归属由服务端从码中查得。

## WebSocket 和提醒

- `/ws?token=<会话令牌>` 握手校验会话，重复 token 参数或无效令牌拒绝（1008，实际握手可能表现为 HTTP 403）。
- 每个连接绑定业务用户；课程、日程、学期事件和调度 `reminder.due` 只投递本人。API Key 兼容连接仅收到默认用户事件。
- 保持现有公开事件信封；内部 `_user_id` 不序列化到消息。发送前复核会话到期/撤销，失效连接关闭 1008；没有事件时闲置连接可以保持到断开，但不能在失效后接收数据。
- 断线、登录更换或重连后 REST 补读；不提供离线事件日志。单 worker/单调度器部署约束不变。
- 微信手机提醒必须来自同用户日程；订阅收件人仍由服务端微信身份决定，设备会话不能冒充微信订阅授权。

## 旧库升级及恢复

1. 先停止后端写入和调度，保留旧代码版本。将当前库路径传给下面脚本（示例路径按部署修改）：

   ```bash
   python scripts/migrate_b8_accounts.py --db /home/idp/idp/backend/data/pet.db --service-stopped
   ```

2. 脚本要求已有库，不会新建指定源文件。自动创建同目录唯一 `pet.pre-b8-<随机值>.db`，只读 SQLite 快照、完整性检查、Linux 权限 600；备份失败立即停止。已有备份绝不覆盖。应用首次启动也有相同迁移保护，生产建议先停服运行脚本。
3. `schema_migrations` 新增版本 3。三类旧业务行全部归用户 1；共享学期设置移为 `user:1`。既有微信身份分配独立业务用户，**不自动认领历史共享业务**。迁移重跑不增加用户、不改原事件 ID、不重复备份已升级库。
4. 旧微信未发送授权（pending/retry/sending）取消并记录 `b8_ownership_migration`，避免把历史共享内容投递给升级后的私人账号；发送历史保留。用户需在本人新日程重新授权。其他业务记录不删除。
5. 版本三升级在事务内执行；为 SQLite 旧非空表添加带默认值的外键列，升级连接暂关外键检查，提交前执行 `foreign_key_check`，失败回滚。正常每个业务连接均启用外键。
6. 恢复不自动覆盖线上库：停服后将验证过的备份复制到**新路径**，用旧代码和临时 `DB_PATH` 验证，再由维护者决定切换；保留升级后的库。共享历史数据迁入个人账号不在此版本自动执行。

## 验证与交接

```bash
python -m pytest backend/tests -q
python scripts/smoke_backend_accounts.py
python scripts/check_c3_integration.py
```

账号 smoke 使用独立回环进程、临时库和模拟微信上游，校验两用户真实 HTTP/WS、配对重放、撤销；不接触生产数据或真实微信。C3 测试适配器为业务调用注入已登录会话，检验原有订阅恢复算法；**不代表 C9 页面登录管道已完成**。

人工复验：A/C 接入后，分别登录两个微信账号；各建一门课、一条带提醒日程。双方列表与学期设置不能串号；复制对方 ID 请求应 404；各连接自己的 WS，仅收到本人事件。用用户甲配对码登录桌宠后只能看到甲的数据，二次兑换应失败；注销后 REST 401。先在隔离库执行迁移并重复一次，核对行数、默认归属、唯一备份及恢复副本。

本地自动验证、GitHub CI 与跨端人工验收分开记录。新用户无历史课程属于隔离结果，不得通过恢复全表读取来“修复”。公网生产使用 HTTPS/WSS；IP/HTTP 仅演示，不能保护账号令牌或配对码。
