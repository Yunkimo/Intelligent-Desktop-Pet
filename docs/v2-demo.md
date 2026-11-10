# V2 演示流程与真机验收

## 本地复现

本地脚本使用临时 SQLite、回环 HTTP 和真实 WebSocket，微信身份由本地替身提供。在仓库根目录运行。脚本所需依赖见 [快速开始](../README.md#快速开始)。

```powershell
.\backend\.venv\Scripts\python.exe scripts/smoke_backend_accounts.py
.\backend\.venv\Scripts\python.exe scripts/smoke_backend_scheduler.py --interval 1 --samples 30 --max-delay 5
.\backend\.venv\Scripts\python.exe -m pytest -c backend/pytest.ini backend/tests/test_capture.py
```

## 微信真机验收

1. 小程序微信登录，在「学期设置」生成配对码。通过桌宠「后端账号」绑定，重用同一配对码应失败。录屏前遮盖账号标识、域名与配对码。
2. 桌宠输入「明天下午三点交报告」。确认前检查气泡和输入框持续可见，选择默认提醒后，在小程序日程页核对待办标题和提醒时间。
3. 在小程序文字入口添加「两分钟后提醒我取快递」。核对标题为「取快递」，等待桌宠显示到期气泡。
4. 使用另一个测试微信账号登录，检查列表和提醒均与原账号隔离。若要验收微信订阅实收，在真机授权并观察微信服务通知，单独记录时刻与通知结果。 [微信接入与订阅说明](c3-subscription.md)
