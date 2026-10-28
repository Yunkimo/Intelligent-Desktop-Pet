"""BackendClient 测试：用假 httpx 隔离网络，验证 URL 拼接、鉴权头与错误包装。"""

import pytest

from pet.backend_client import BackendClient, BackendError


class _Resp:
    def __init__(self, status_code: int, json_data=None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        return self._json


def test_list_courses_builds_url_and_header(monkeypatch):
    captured: dict = {}

    def fake_request(method, url, headers, json, timeout, trust_env=False):
        captured.update(
            method=method, url=url, headers=headers, json=json, timeout=timeout, trust_env=trust_env
        )
        return _Resp(200, [{"id": 1, "name": "高等数学"}])

    monkeypatch.setattr("pet.backend_client.httpx.request", fake_request)
    client = BackendClient("http://127.0.0.1:8001/", "secret")

    assert client.list_courses() == [{"id": 1, "name": "高等数学"}]
    assert captured["url"] == "http://127.0.0.1:8001/api/courses"
    assert captured["headers"] == {"X-API-Key": "secret"}
    assert captured["method"] == "GET"
    assert captured["trust_env"] is False  # 本地后端必须绕过系统代理（Clash 会拦成 502）


def test_create_reminder_sends_payload(monkeypatch):
    sent: dict = {}

    def fake_request(method, url, headers, json, timeout, trust_env=False):
        sent["json"] = json
        return _Resp(201, {"id": 7, "title": "喝水"})

    monkeypatch.setattr("pet.backend_client.httpx.request", fake_request)
    client = BackendClient("http://h", "tok")

    result = client.create_reminder("喝水", "2026-10-11T10:00:00", body="起来走走", channel="pc")
    assert result == {"id": 7, "title": "喝水"}
    assert sent["json"] == {
        "title": "喝水",
        "body": "起来走走",
        "remind_at": "2026-10-11T10:00:00",
        "channel": "pc",
        "task_id": None,
    }


def test_delete_returns_none_on_204(monkeypatch):
    def fake_request(method, url, headers, json, timeout, trust_env=False):
        return _Resp(204)

    monkeypatch.setattr("pet.backend_client.httpx.request", fake_request)
    assert BackendClient("http://h", "tok").delete_task(3) is None


def test_non_2xx_raises_backend_error(monkeypatch):
    def fake_request(method, url, headers, json, timeout, trust_env=False):
        return _Resp(401, text="API Key 无效")

    monkeypatch.setattr("pet.backend_client.httpx.request", fake_request)
    with pytest.raises(BackendError, match="401"):
        BackendClient("http://h", "bad").list_tasks()


def test_network_error_wrapped(monkeypatch):
    import httpx

    def fake_request(method, url, headers, json, timeout, trust_env=False):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("pet.backend_client.httpx.request", fake_request)
    with pytest.raises(BackendError, match="后端不可达"):
        BackendClient("http://h", "tok").health()


def test_non_json_2xx_wrapped(monkeypatch):
    class _BadJsonResp:
        status_code = 200
        text = "<html>oops</html>"

        def json(self):
            raise ValueError("no json")

    monkeypatch.setattr("pet.backend_client.httpx.request", lambda *a, **k: _BadJsonResp())
    with pytest.raises(BackendError, match="不是合法 JSON"):
        BackendClient("http://h", "tok").list_tasks()


def test_crud_wrappers_use_request(monkeypatch):
    calls: list = []

    def fake_request(method, url, headers, json, timeout, trust_env=False):
        calls.append((method, url, json))
        return _Resp(200, {"ok": True})

    monkeypatch.setattr("pet.backend_client.httpx.request", fake_request)
    c = BackendClient("http://h", "tok")

    c.create_course("数学", 1, "08:00", "09:40", location="A101", weeks=[1, 2])
    c.update_course(3, name="语文")
    c.delete_course(3)
    c.update_task(5, done=True)
    c.list_reminders()
    c.update_reminder(7, channel="pc")
    c.delete_reminder(7)

    assert [m for m, _, _ in calls] == ["POST", "PUT", "DELETE", "PUT", "GET", "PUT", "DELETE"]


def test_build_ws_url_schemes():
    from pet.backend_client import build_ws_url

    assert build_ws_url("http://127.0.0.1:8001", "tok") == "ws://127.0.0.1:8001/ws?token=tok"
    assert build_ws_url("https://api.x.com", "tok") == "wss://api.x.com/ws?token=tok"
    assert build_ws_url("127.0.0.1:8001", "tok") == "ws://127.0.0.1:8001/ws?token=tok"


def test_parse_event_rejects_non_json_and_non_dict():
    from pet.backend_client import parse_event

    assert parse_event("not json") is None
    assert parse_event("[1, 2]") is None
    assert parse_event('{"type":"task.created"}') == {"type": "task.created"}
