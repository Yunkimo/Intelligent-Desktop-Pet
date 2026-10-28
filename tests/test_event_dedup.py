"""实际窗口事件入口的去重、重连状态、异常与容量边界。"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pet.backend_client import WsListener
from pet.event_cache import RecentEvents
from pet.window import PetWindow


def event(event_id="first", **updates):
    return {
        "version": 1,
        "event_id": event_id,
        "type": "reminder.due",
        "data": {"id": 7},
        **updates,
    }


def receiver(capacity=1024):
    return SimpleNamespace(
        _recent_events=RecentEvents(capacity),
        _reminder_text=Mock(return_value="到期提醒"),
        _remind_health=Mock(),
        show_hint=Mock(),
    )


def test_retry_does_not_repeat_rest_bubble_or_voice():
    target = receiver()
    PetWindow._on_backend_event(target, event())
    PetWindow._on_backend_event(target, event())
    target._reminder_text.assert_called_once_with(7)
    target._remind_health.assert_called_once_with("到期提醒")


def test_rescheduled_resource_with_new_event_id_is_shown():
    target = receiver()
    for item in (event(), event("rescheduled"), event()):
        PetWindow._on_backend_event(target, item)
    assert target._remind_health.call_count == 2


def test_lru_is_bounded_and_recent_duplicate_stays_cached():
    target = receiver(2)
    for key in ("a", "b", "a", "c", "a", "b"):
        PetWindow._on_backend_event(target, event(key))
    assert target._remind_health.call_count == 4
    assert len(target._recent_events._ids) == 2


def test_failed_handler_can_retry_same_event():
    target = receiver()
    target._remind_health.side_effect = [RuntimeError("display failed"), None]
    with pytest.raises(RuntimeError):
        PetWindow._on_backend_event(target, event())
    PetWindow._on_backend_event(target, event())
    assert target._remind_health.call_count == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 2},
        {"event_id": None},
        {"event_id": ""},
        {"event_id": "x" * 129},
        {"data": []},
        {"data": {"id": True}},
        {"data": {"id": 0}},
        {"type": "unknown"},
    ],
)
def test_invalid_event_does_not_consume_id_or_show(changes):
    target = receiver()
    PetWindow._on_backend_event(target, event(**changes))
    target._remind_health.assert_not_called()
    PetWindow._on_backend_event(target, event())
    target._remind_health.assert_called_once()


@pytest.mark.parametrize("kind", ["task.created", "course.created"])
def test_creation_notifications_are_also_deduplicated(kind):
    target = receiver()
    PetWindow._on_backend_event(target, event(type=kind))
    PetWindow._on_backend_event(target, event(type=kind))
    target.show_hint.assert_called_once()


def test_reconnect_keeps_window_cache(qapp, monkeypatch):
    target = receiver()
    streams = iter([[event()], [event(), event("new")]])
    connections = []

    class Connection:
        def __init__(self, frames):
            self.frames = iter(frames)

        def settimeout(self, _timeout):
            pass

        def recv(self):
            frame = next(self.frames, None)
            return json.dumps(frame) if frame else ""

        def close(self):
            pass

    def connect(*args, **kwargs):
        connection = Connection(next(streams))
        connections.append(connection)
        return connection

    monkeypatch.setattr("pet.backend_client.websocket.create_connection", connect)
    listener = WsListener("ws://test/ws")
    listener._RECONNECT_SECS = 0
    received = []

    def handle(item):
        received.append(item)
        PetWindow._on_backend_event(target, item)
        if len(received) == 3:
            listener.request_stop()

    listener.event.connect(handle)
    listener.run()
    assert len(connections) == 2
    assert target._remind_health.call_count == 2
