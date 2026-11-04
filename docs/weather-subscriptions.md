# 微信带伞提醒后端接入契约

成员 B，2026-11-04。依赖天气查询、微信登录和一次性订阅能力。默认城市长沙。

## 时间与通知渠道

用户主动订阅的是本次事件：服务端按 Asia/Shanghai 确定今晚 21:00 和明天日期。
21:00 前等待；21:00 后登记，当晚有效期内可立即检查发送；当天午夜过期，不转移授权到第二天。
雨雪雷暴等降水才发一条微信订阅消息；无雨不发；天气不可用每 5 分钟重查，到午夜停止。
用户关闭小程序和桌宠不影响后端调度。一次授权不代表永久每天推送。

公开预报仍使用 GET /api/weather/tomorrow?city=长沙，支持普通业务会话。
本文件的订阅接口必须使用微信登录返回的 session_token，不接受共享 API Key 或桌宠设备会话。
所有接口携带 Authorization: Bearer <session_token>，用户身份与 openid 均来自后端。

## C 的完整调用顺序

### 准备事件

```http
POST /api/weather/subscriptions
Content-Type: application/json

{"city":"长沙"}
```

返回 201。相同微信用户、规范化大小写城市、目标日期重复准备返回同一 event_id。
city 可省略，默认长沙；不接受前端指定日期、用户 ID、openid、发送时间。

```json
{
  "event_id":"<UUID>", "city":"长沙", "target_date":"2026-11-05",
  "send_at":1793797200.0, "expires_at":1793808000.0,
  "template_id":"<服务器配置的公开模板ID>", "choice":null,
  "status":"prepared", "attempts":0, "weather_attempts":0,
  "last_error":null, "sent_at":null, "created_at":1793780000.0, "forecast":null
}
```

时间数字仅为结构示例；实际以服务器响应为准，均为 Unix 秒，前端转毫秒后按上海时区显示。
在用户点击订阅前准备好事件和 template_id；点击时直接调用 wx.requestSubscribeMessage，避免异步准备导致手势失效。

### 登记微信返回的授权选择

```http
POST /api/weather/subscriptions/<event_id>/authorization
Content-Type: application/json

{"request_id":"<本次操作固定的UUID>","template_id":"<准备接口返回值>","result":"accept"}
```

result 仅允许 accept/reject/ban/filter。accept 后 status=pending；其余为 rejected。
登记失败或结果不明时保存原 request_id、event_id、模板和选择，用原参数重放或查询状态。
同一 request_id 同参数重放返回当前事件状态；不同参数返回 409 idempotency_conflict。
不同 request_id 不会使同一已登记事件重复发送，返回 409 weather_event_already_registered。
rejected 或尚未开始发送的 cancelled 事件可在用户再次主动授权后用新 request_id 登记。
sent/uncertain/failed/no_rain 等终态不自动重新授权或重发。

前端申报 accept 仅表示用户报告已授权，微信发送 API 才最终判定权限。

### 查询和取消

```http
GET /api/weather/subscriptions
GET /api/weather/subscriptions/<event_id>
DELETE /api/weather/subscriptions/<event_id>
```

列表最多返回本人最近 100 个事件。详情可用于历史通知，不能用“当前明天”接口覆盖旧事件日期。
准备、登记、查询响应包含 forecast（最后一次天气判断快照），不包含 openid、凭据或他人数据。
取消 checking/pending/retry 等尚未发送事件会阻止后续发送。sending/sent/uncertain 返回
409 weather_send_already_started，不声称撤回已出站请求。其他用户访问事件返回 404。

### 状态和前端文案

| status | 含义与建议展示 |
|---|---|
| prepared | 待用户主动授权 |
| pending | 已登记本次授权，等待检查 |
| checking | 正在检查天气 |
| retry_weather | 天气暂不可用，稍后重查 |
| sending | 微信发送中，不能保证可取消 |
| retry | 明确未发送的可恢复错误，有限重试 |
| sent | 微信 API 已接受，不等同手机已展示；实收单独验证 |
| no_rain | 本次无降水，不发送 |
| rejected | 本次未取得用户接受申报 |
| cancelled | 后续处理已取消 |
| expired | 已过当晚有效期 |
| failed | 明确发送失败；查看 last_error，例如 wechat_no_subscription |
| uncertain | 发送结果不明，不自动重发或要求用户盲目再授权 |

接口常见错误：401 微信会话无效；404 非本人或不存在；409 事件冲突/过期/已发送；
422 非法输入；503 微信或独立天气模板未配置。普通天气卡片仍可在订阅不可用时使用。

## 微信模板与落地页

天气消息独立读取以下配置，日程消息的 WX_TEMPLATE_ID/WX_TEMPLATE_FIELDS 不改变：

```dotenv
WEATHER_WX_TEMPLATE_ID=<账号中已存在的适用模板ID>
WEATHER_WX_TEMPLATE_FIELDS={"thing2":"title","date4":"target_date","thing10":"city"}
WEATHER_WX_PAGE=pages/index/index
```

已只读核对生产账号现有「日程提醒」模板，含 thing2 提醒内容、date4 日程时间、thing10 地点。
本功能作为用户主动订阅的一次提醒，内容填写“明日带伞提醒”、目标天气日期、订阅城市。
字段映射允许 thingN 对应 title/city/tip，dateN 对应 target_date；thing 字段最多 20 字。
如更换模板先核对小程序服务类目和模板适用性，不沿用不匹配的字段。

消息点击地址为 pages/index/index?weather_event_id=<UUID>。
C 在首页 onLoad 保存参数，经统一登录恢复后调用上述本人详情接口，打开天气详情视图。
后续可将 WEATHER_WX_PAGE 改为已发布的专用页面，C/B 同步改动，避免微信 invalid_page。

## 后端一致性与运行

schema 5 新增 weather_subscriptions、weather_subscription_requests，两张表独立于用户日程。
迁移前唯一备份，迁移事务化且幂等。新发送逻辑挂入原有单实例微信调度循环，
不依赖 WEATHER_TIP_ENABLED 的演示城市预取开关，不受桌宠是否在线影响。
每轮最多处理 4 条天气事件，普通微信日程先处理，桌面 WS 调度保持独立。

发送前事务复核取消、目标日期、模板及有效期；同事件只有一次领取可进入 sending。
天气查询中断可安全重查；发送阶段中断/超时/结果不明进入 uncertain，不自动重复消费订阅。
仅明确尚未发送的可恢复错误按原有限重试配置处理，达到上限转 failed。
微信授权和天气缓存互相独立，无雨或未知时不调用微信发送。

## 验收边界

本地测试使用临时数据库、Mock 天气与 Mock 微信，覆盖真实 HTTP 登记、账号隔离、
幂等、雨晴未知、21 点/午夜、取消、重启、有限重试、模板负载及迁移备份。
部署自检验证健康、接口、配置及迁移；不向没有主动授权的真实用户发送测试消息。
真正手机收到消息及点击落地页，由 C 接入授权界面后与 B 真机联调记录。
