"""tools 注册表测试：用假后端验证工具绑定与结果格式化，隔离网络。"""

from pet.tools import build_tools, tool_schema


class _FakeBackend:
    def __init__(self) -> None:
        self.courses: list[dict] = []
        self.tasks: list[dict] = []
        self.created_tasks: list[dict] = []
        self.reminder: dict | None = None

    def list_courses(self):
        return self.courses

    def list_tasks(self):
        return self.tasks

    def create_task(self, title, note="", due_at=None, remind_at=None):
        self.created_tasks.append(
            {"title": title, "note": note, "due_at": due_at, "remind_at": remind_at}
        )
        return {"id": 1, "title": title}

    def update_task(self, task_id, **fields):
        self.updated = (task_id, fields)

    def delete_task(self, task_id):
        self.deleted = task_id

    def create_reminder(self, title, remind_at, body="", channel="both", task_id=None):
        self.reminder = {"title": title, "remind_at": remind_at, "body": body, "channel": channel}


def test_build_tools_has_expected_names():
    tools = build_tools(_FakeBackend())
    expected = {
        "list_courses",
        "list_tasks",
        "create_task",
        "update_task",
        "delete_task",
        "create_reminder",
        "get_weather",
        "web_search",
    }
    assert expected <= set(tools)


def test_list_courses_formats():
    b = _FakeBackend()
    b.courses = [
        {
            "name": "高等数学",
            "day_of_week": 1,
            "start_time": "08:00",
            "end_time": "09:40",
            "location": "A101",
        }
    ]
    out = build_tools(b)["list_courses"].fn()
    assert "高等数学" in out
    assert "周1 08:00-09:40" in out


def test_create_task_calls_backend():
    b = _FakeBackend()
    tools = build_tools(b)
    result = tools["create_task"].fn(title="复习英语", due_at="2026-10-12T09:00:00")
    assert result == "已新增日程「复习英语」"
    assert b.created_tasks[0]["title"] == "复习英语"
    assert b.created_tasks[0]["due_at"] == "2026-10-12T09:00:00"


def test_create_reminder_calls_backend():
    b = _FakeBackend()
    tools = build_tools(b)
    tools["create_reminder"].fn(title="喝水", remind_at="2026-10-11T10:00:00", channel="pc")
    assert b.reminder["title"] == "喝水"
    assert b.reminder["channel"] == "pc"


def test_update_and_delete_task():
    b = _FakeBackend()
    tools = build_tools(b)
    assert tools["update_task"].fn(task_id=2, done=True) == "已更新日程 #2"
    assert b.updated == (2, {"done": True})
    assert tools["delete_task"].fn(task_id=2) == "已删除日程 #2"
    assert b.deleted == 2


def test_create_task_normalizes_natural_time(monkeypatch):
    b = _FakeBackend()
    monkeypatch.setattr("pet.tools.normalize_datetime", lambda v: "2026-10-13T09:00:00")
    tools = build_tools(b)
    tools["create_task"].fn(title="复习", due_at="明天 9:00")
    assert b.created_tasks[0]["due_at"] == "2026-10-13T09:00:00"


def test_create_reminder_normalizes_natural_time(monkeypatch):
    b = _FakeBackend()
    monkeypatch.setattr("pet.tools.normalize_datetime", lambda v: "2026-10-12T18:00:00")
    tools = build_tools(b)
    tools["create_reminder"].fn(title="喝水", remind_at="今天 18:00")
    assert b.reminder["remind_at"] == "2026-10-12T18:00:00"


def test_tool_schema_shape():
    tools = build_tools(_FakeBackend())
    schema = tool_schema(tools["create_task"])
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "create_task"
    assert "title" in schema["function"]["parameters"]["properties"]


def test_list_courses_missing_fields_no_keyerror():
    b = _FakeBackend()
    b.courses = [{"name": "缺字段课"}]
    out = build_tools(b)["list_courses"].fn()
    assert "缺字段课" in out  # 缺失字段用默认占位，不抛 KeyError


def test_list_tasks_missing_fields_no_keyerror():
    b = _FakeBackend()
    b.tasks = [{"title": "缺 ID 的日程"}]
    out = build_tools(b)["list_tasks"].fn()
    assert "缺 ID 的日程" in out
    assert "#?" in out


def test_list_courses_empty_placeholder():
    assert build_tools(_FakeBackend())["list_courses"].fn() == "（还没有课表）"


def test_list_tasks_empty_placeholder():
    assert build_tools(_FakeBackend())["list_tasks"].fn() == "（还没有日程）"


def test_get_weather_failure_returns_message(monkeypatch):
    import httpx

    def boom(*_a, **_k):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(httpx, "get", boom)
    out = build_tools(_FakeBackend())["get_weather"].fn(city="北京")
    assert "查天气失败" in out


def test_web_search_failure_returns_message(monkeypatch):
    import ddgs

    class _Boom:
        def text(self, query, max_results=5):
            raise RuntimeError("network down")

    monkeypatch.setattr(ddgs, "DDGS", _Boom)
    out = build_tools(_FakeBackend())["web_search"].fn(query="hello")
    assert "失败" in out


# ---------- 天气：今天 / 明天 / 后天 / 一周 ----------
def _forecast_payload() -> dict:
    return {
        "current": {"temperature_2m": 7.9, "apparent_temperature": 5.8},
        "daily": {
            "time": [
                "2026-10-30",
                "2026-10-31",
                "2026-11-01",
                "2026-11-02",
                "2026-11-03",
                "2026-11-04",
                "2026-11-05",
            ],
            "weather_code": [0, 3, 3, 0, 2, 3, 0],
            "temperature_2m_max": [19.5, 10.6, 16.3, 14.7, 16.5, 14.0, 12.6],
            "temperature_2m_min": [6.6, 3.8, 4.6, 4.5, 4.8, 6.0, 3.4],
        },
    }


def _weather_tool(monkeypatch, forecast=None, geo=None):
    import pet.tools as tools_module

    tools_module._GEO_CACHE.clear()
    geo = (
        geo
        if geo is not None
        else {"results": [{"name": "北京", "latitude": 39.9, "longitude": 116.4}]}
    )
    forecast = forecast if forecast is not None else _forecast_payload()
    calls: list[str] = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        calls.append(url)
        if "geocoding" in url:
            return _Resp(geo)
        return _Resp(forecast)

    monkeypatch.setattr(tools_module.httpx, "get", fake_get)
    return tools_module.build_tools(_FakeBackend())["get_weather"].fn, calls


def test_weather_today_reports_current_and_range(monkeypatch):
    fn, _ = _weather_tool(monkeypatch)
    text = fn(city="北京")
    assert "北京 今天（2026-10-30）" in text
    assert "晴" in text
    assert "6.6~19.5°C" in text
    assert "当前 7.9°C" in text and "体感 5.8°C" in text


def test_weather_tomorrow_reports_forecast_only(monkeypatch):
    fn, _ = _weather_tool(monkeypatch)
    text = fn(city="北京", day="明天")
    assert "北京 明天（2026-10-31）" in text
    assert "阴" in text and "3.8~10.6°C" in text
    assert "当前" not in text


def test_weather_day_after_and_fourth_day(monkeypatch):
    fn, _ = _weather_tool(monkeypatch)
    assert "2026-11-01" in fn(city="北京", day="后天")
    assert "大后天" in fn(city="北京", day="大后天")


def test_weather_week_lists_seven_days(monkeypatch):
    fn, _ = _weather_tool(monkeypatch)
    lines = fn(city="北京", day="未来一周").splitlines()
    assert lines[0].startswith("北京 未来 7 天")
    assert len(lines) == 8  # 标题 + 7 天
    assert "2026-10-30 周五：晴，6.6~19.5°C" in lines[1]
    assert "2026-11-05 周四" in lines[-1]


def test_weather_unknown_day_falls_back_to_today(monkeypatch):
    fn, _ = _weather_tool(monkeypatch)
    assert "北京 今天" in fn(city="北京", day="下周")


def test_weather_unknown_city_is_reported(monkeypatch):
    fn, _ = _weather_tool(monkeypatch, geo={"results": []})
    assert "查不到" in fn(city="火星")


def test_weather_missing_daily_is_reported(monkeypatch):
    fn, _ = _weather_tool(monkeypatch, forecast={"daily": {}})
    assert "查不到" in fn(city="北京")


def test_weather_geocode_result_is_cached(monkeypatch):
    fn, calls = _weather_tool(monkeypatch)
    fn(city="北京", day="明天")
    before = len(calls)
    fn(city="北京", day="后天")
    assert len(calls) == before + 1  # 第二次只请求预报，不再地理编码


def test_weather_accepts_weekday_name(monkeypatch):
    fn, _ = _weather_tool(monkeypatch)
    text = fn(city="北京", day="星期日")
    assert "周日（2026-11-01）" in text


def test_weather_accepts_chinese_relative_day(monkeypatch):
    fn, _ = _weather_tool(monkeypatch)
    assert "2026-11-02" in fn(city="北京", day="三天后")


def test_weather_accepts_month_day(monkeypatch):
    fn, _ = _weather_tool(monkeypatch)
    assert "2026-11-02" in fn(city="北京", day="11月2日")


def test_weather_accepts_iso_date(monkeypatch):
    fn, _ = _weather_tool(monkeypatch)
    text = fn(city="北京", day="2026-11-03")
    assert "周二（2026-11-03）" in text


def test_weather_out_of_range_date_falls_back_to_today(monkeypatch):
    fn, _ = _weather_tool(monkeypatch)
    assert "北京 今天" in fn(city="北京", day="2026-12-24")
