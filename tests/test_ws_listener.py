"""WsListener 与地址/解析工具测试：用假连接隔离真实网络。"""

from pet.backend_client import WsListener, build_ws_url, parse_event


def test_build_ws_url_http():
    assert build_ws_url("http://127.0.0.1:8001", "secret") == "ws://127.0.0.1:8001/ws?token=secret"


def test_build_ws_url_https_and_encoding():
    assert build_ws_url("https://example.com", "s ecret") == "wss://example.com/ws?token=s+ecret"


def test_build_ws_url_strips_trailing_slash():
    assert build_ws_url("http://host:8001/", "tok") == "ws://host:8001/ws?token=tok"


def test_parse_event_valid_and_invalid():
    assert parse_event('{"type":"reminder.due","data":{"id":1}}') == {
        "type": "reminder.due",
        "data": {"id": 1},
    }
    assert parse_event("not json") is None
    assert parse_event("[1,2,3]") is None  # 非对象忽略


def test_run_emits_event(qapp, monkeypatch):
    frames = ['{"type":"reminder.due","data":{"id":7}}']

    class _Timeout(Exception):
        pass

    class _FakeWs:
        def settimeout(self, t):
            pass

        def recv(self):
            if frames:
                return frames.pop(0)
            raise _Timeout()

        def close(self):
            pass

    monkeypatch.setattr(
        "pet.backend_client.websocket.create_connection", lambda url, timeout: _FakeWs()
    )
    monkeypatch.setattr("pet.backend_client.websocket.WebSocketTimeoutException", _Timeout)

    listener = WsListener("ws://x/ws")
    got: list[dict] = []

    def on_event(evt):
        got.append(evt)
        listener.request_stop()

    listener.event.connect(on_event)
    listener.run()  # 同步运行：收到事件后 stop
    assert got == [{"type": "reminder.due", "data": {"id": 7}}]


def test_create_failure_emits_error_and_stops(qapp, monkeypatch):
    def boom(url, timeout):
        raise ConnectionError("refused")

    monkeypatch.setattr("pet.backend_client.websocket.create_connection", boom)

    listener = WsListener("ws://x/ws")
    errors: list[str] = []

    def on_error(msg):
        errors.append(msg)
        listener.request_stop()

    listener.error.connect(on_error)
    listener.run()
    assert errors == ["refused"]
