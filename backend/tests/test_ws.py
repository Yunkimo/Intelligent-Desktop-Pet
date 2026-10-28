"""WebSocket 契约、鉴权、提交后通知与连接生命周期回归。"""

import asyncio
import logging
from datetime import datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from app import config, db
from app.logging_config import QueryTokenFilter
from app.main import app
from app.push_service import Event, PushService
from fastapi import WebSocketDisconnect
from pydantic import ValidationError


@pytest.mark.parametrize("query", ["", "?token=wrong", "?token=", "?token=test-token&token=wrong"])
def test_invalid_credentials(client, query):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws" + query):
            pytest.fail("握手不应成功")
    assert exc.value.code == 1008
    assert app.state.push_service.connection_count == 0


def test_unconfigured_credentials(client, monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", "")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=test-token"):
            pytest.fail("未配置密钥不应接受连接")


@pytest.mark.parametrize(
    ("path", "payload", "event_type"),
    [
        ("tasks", {"title": "联调日程"}, "task.created"),
        (
            "courses",
            {"name": "数学", "day_of_week": 1, "start_time": "08:00", "end_time": "09:00"},
            "course.created",
        ),
    ],
)
def test_two_clients_receive_committed_creation(client, path, payload, event_type):
    with client.websocket_connect("/ws?token=test-token") as first:
        with client.websocket_connect("/ws?token=test-token") as second:
            response = client.post(
                f"/api/{path}", json=payload, headers={"X-API-Key": "test-token"}
            )
            assert response.status_code == 201
            event = first.receive_json()
            assert event == second.receive_json()
            assert event["version"] == 1
            UUID(event["event_id"])
            occurred_at = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
            assert occurred_at.utcoffset().total_seconds() == 0
            assert event["type"] == event_type
            assert event["data"] == {"id": response.json()["id"]}
            rows = client.get(f"/api/{path}", headers={"X-API-Key": "test-token"}).json()
            assert response.json() in rows
    assert app.state.push_service.connection_count == 0


def test_http_get_is_not_websocket(client):
    assert client.get("/ws?token=test-token").status_code == 404


def test_client_cannot_publish_events(client):
    with client.websocket_connect("/ws?token=test-token") as connection:
        connection.send_json({"type": "task.created", "data": {"id": 999}})
        with pytest.raises(WebSocketDisconnect) as exc:
            connection.receive_json()
        assert exc.value.code == 1008
    assert app.state.push_service.connection_count == 0


def test_notification_failure_does_not_fail_committed_write(client, monkeypatch):
    monkeypatch.setattr(app.state.push_service, "broadcast", AsyncMock(side_effect=RuntimeError))
    response = client.post(
        "/api/tasks", json={"title": "保留写入"}, headers={"X-API-Key": "test-token"}
    )
    assert response.status_code == 201
    assert db.list_tasks() == [response.json()]


def test_failed_database_write_does_not_notify(client, monkeypatch):
    notify = AsyncMock()
    monkeypatch.setattr(app.state.push_service, "notify", notify)
    monkeypatch.setattr(
        db, "create_task", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("DB"))
    )
    with pytest.raises(RuntimeError, match="DB"):
        client.post("/api/tasks", json={"title": "失败"}, headers={"X-API-Key": "test-token"})
    notify.assert_not_awaited()


class Socket:
    """用可控阻塞模拟网络，验证隔离、取消与关闭边界。"""

    def __init__(self, *, blocked=False, error=None, close_blocked=False):
        self.accept = AsyncMock()
        self.close = AsyncMock(side_effect=self._close)
        self.messages = []
        self.blocked = blocked
        self.error = error
        self.close_blocked = close_blocked
        self.entered = asyncio.Event()
        self.delivered = asyncio.Event()
        self.sending = False

    async def _close(self, code):
        if self.close_blocked:
            await asyncio.Event().wait()

    async def send_text(self, message):
        assert not self.sending, "同一连接不能并发发送"
        self.sending = True
        try:
            self.entered.set()
            if self.error:
                raise self.error
            if self.blocked:
                await asyncio.Event().wait()
            await asyncio.sleep(0)
            self.messages.append(message)
            self.delivered.set()
        finally:
            self.sending = False


def test_slow_and_failed_clients_do_not_block_healthy_client():
    async def scenario():
        push = PushService(1, 0.02)
        healthy, slow = Socket(), Socket(blocked=True, close_blocked=True)
        broken = Socket(error=WebSocketDisconnect(1006))
        for socket in (healthy, slow, broken):
            await push.connect(socket)
        task = asyncio.create_task(push.broadcast({"type": "task.created", "data": {"id": 1}}))
        await asyncio.wait_for(healthy.delivered.wait(), 0.5)
        assert not task.done()
        assert await asyncio.wait_for(task, 2) == 1
        assert push.connection_count == 1
        slow.close.assert_awaited_once_with(code=1013)
        broken.close.assert_awaited_once_with(code=1013)
        await push.close_all()

    asyncio.run(scenario())


def test_duplicate_registration_concurrent_broadcast_and_shutdown():
    async def scenario():
        push = PushService(1, 0.1)
        socket = Socket()
        await push.connect(socket)
        await push.connect(socket)
        socket.accept.assert_awaited_once()
        assert push.connection_count == 1
        await asyncio.gather(
            *(push.broadcast({"type": "task.created", "data": {"id": n}}) for n in range(1, 6))
        )
        assert len(socket.messages) == 5
        await push.close_all()
        await push.close_all()
        socket.close.assert_awaited_once_with(code=1001)
        late = Socket()
        assert not await push.connect(late)
        late.accept.assert_not_awaited()
        assert push.connection_count == 0

    asyncio.run(scenario())


def test_shutdown_during_handshake_does_not_leak_connection():
    async def scenario():
        push = PushService(1, 0.1)
        socket = Socket()
        accepting = asyncio.Event()
        resume = asyncio.Event()

        async def accept():
            accepting.set()
            await resume.wait()

        socket.accept = accept
        task = asyncio.create_task(push.connect(socket))
        await accepting.wait()
        await push.close_all()
        resume.set()
        assert not await task
        assert push.connection_count == 0
        socket.close.assert_awaited_once_with(code=1001)

    asyncio.run(scenario())


def test_registry_mutation_and_cancelled_send_cleanup():
    async def scenario():
        push = PushService(2, 0.1)
        slow = Socket(blocked=True)
        await push.connect(slow)
        task = asyncio.create_task(push.broadcast({"type": "reminder.due", "data": {"id": 1}}))
        await slow.entered.wait()
        healthy = Socket()
        await push.connect(healthy)
        push.disconnect(slow)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        slow.close.assert_awaited_once_with(code=1001)
        assert await push.broadcast({"type": "course.created", "data": {"id": 2}}) == 1
        await push.close_all()

    asyncio.run(scenario())


def test_invalid_event_rejected_before_send():
    async def scenario():
        push = PushService(1, 1)
        assert await push.broadcast({"type": "task.created", "data": {"id": 1}}) == 0
        with pytest.raises(ValidationError):
            await push.broadcast({"type": "unknown", "data": {"id": 1}})
        with pytest.raises(ValidationError):
            Event(type="task.created", data={"id": 1}, occurred_at="2026-10-11T00:00:00")

    asyncio.run(scenario())


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "bad"])
def test_timeout_configuration_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("WS_SEND_TIMEOUT_SECONDS", value)
    with pytest.raises(ValueError, match="WS_SEND_TIMEOUT_SECONDS"):
        config.positive_seconds("WS_SEND_TIMEOUT_SECONDS", "2")


@pytest.mark.parametrize("query", ["token=secret", "%74oken=secret", "token=a&token=secret"])
def test_query_redaction(query):
    record = logging.LogRecord(
        "uvicorn.error", logging.INFO, "", 0, '%s - "WebSocket %s"', ("peer", "/ws?" + query), None
    )
    assert QueryTokenFilter().filter(record)
    assert "secret" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()
