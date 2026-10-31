# B7 接口与服务器验收

## C7 课表图片

沿用 POST /api/courses/parse-image、X-API-Key 和 multipart 字段 image。支持 JPEG/PNG，最大 10 MiB、1600 万像素、100 个课程格。默认 60 秒包含服务端收取 multipart 和模型调用，由 PARSE_TIMEOUT_SECONDS 控制。上传前的客户端压缩、客户端网络和反向代理排队应单独计时。一次图片至多调用模型一次。服务端记录上传读取、模型、结果处理的毫秒数。

200 响应的 courses 是时间完整且通过课程校验的条目。pending_courses 是待确认草稿，保留课程名、星期、教师、地点、weeks、slot 及 needs_confirmation（time/weeks/day_of_week）。没有时刻时 start_time/end_time 为 null。C7 根据用户确认的节次表映射或手填，再送现有 bulk 接口。请展示两个列表和 warnings，skipped 代表重复、无效或无匹配的条目。只有待补项也会返回 200。识别和展示草稿都不写数据库。

413 需缩小图片，422 需修正输入，503 需检查服务配置；504 的 detail.code=parse_timeout，429 为 rate_limited，502 为其他上游异常。客户端默认最多等待 70 秒，取消后忽略迟到响应。C7 确认保存后按已有 bulk 契约核对 created/skipped。

## C8 文本日程

POST /api/tasks/parse-text，沿用 tasks 鉴权。请求样例：

```json
{"text":"明天下午三点提醒我交实验报告；下周五前交报告","reference_at":"2026-10-30T12:00:00+08:00","timezone":"Asia/Shanghai"}
```

drafts 含两项：第一项 remind_at 为 2026-10-31T15:00:00+08:00，第二项 due_at 为 2026-11-06 且 remind_at=null。每项保留 source、title、note、due_at、remind_at、needs_confirmation。可用“备注：附源代码”填写备注。最多 2000 字、20 项，reference_at 必须带偏移，timezone 为 IANA 名称。

规则支持今明后/昨天、本周/下周某天、YYYY-MM-DD、中文整点和半点、24 小时时刻。日期不明、时刻不明及过去时间分别标记 date、time/remind_at、past。请展示原文并允许用户修改；明确的截止日期不自动生成提醒。分号、换行等拆分多个事项；可选 LLM_TEXT_MODEL 用于复杂连接句的断句，复用视觉服务的地址和凭据。模型仅返回按顺序拼回原文的片段，错误输出返回 502。C8 确认后仅将 title、note、due_at、remind_at 交给 POST /api/tasks，复用 B5；微信授权沿用 C3。

## 真实模型基准

样例 tests_fixtures/b7/schedule.png 使用合成教师和教室，expected.json 是 14 个课程格的标准答案。图片没有时刻，含单双周、离散周、同名课程和空格。服务器验收包附带 B6 基线 vision.py 和新版代码。解压到新目录后，在该目录执行：

```bash
/home/idp/venvs/idp/bin/python scripts/benchmark_b7.py --baseline-vision baseline_vision.py --env-file /home/idp/idp/backend/.env --output b7-result.json
```

脚本从指定配置读取模型名、服务地址及 Key。在内存中对同一图片交替测两版各 5 次，逐次保存时间、成功/异常类型、全部识别条目、与标准答案一致数和缺时间条目数。报告比较成功样本中位数及各版所有样本最大值。两版全部成功才计算降幅和 30% 速度目标。人工还需核对每个缺时间条目的 slot、警告和 14 个课程格准确性。此耗时是服务端解析函数到真实上游再返回草稿的耗时。小程序端耗时由 C7 单独测量。脚本不会启动或重启线上服务。

本地复验：在后端虚拟环境运行 python -m pytest -c backend/pytest.ini backend/tests -q。覆盖真实 FastAPI 路由、SQLite、规则样例、确认后生成单条 PC 提醒、图片等待上限、上游断网/限流/错误输出和无凭据运行规则。真实模型性能在取得服务器输出后记录。
