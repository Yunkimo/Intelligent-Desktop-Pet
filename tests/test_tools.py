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
