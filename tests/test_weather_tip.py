"""天气提示测试：到点触发一次、跨天复位、有雨才发 tip。"""

from datetime import datetime

from pet.weather_tip import WeatherTipMonitor, WeatherTipWorker


class _FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def _monitor(hour, fired, clock) -> WeatherTipMonitor:
    monitor = WeatherTipMonitor(hour, clock=clock)
    monitor.check_due.connect(lambda: fired.append(1))
    return monitor


def test_fires_once_per_day():
    fired = []
    clock = _FakeClock(datetime(2026, 11, 4, 21, 30))
    monitor = _monitor(21, fired, clock)

    monitor._check()
    monitor._check()

    assert len(fired) == 1  # 同一天只触发一次


def test_no_fire_before_hour():
    fired = []
    clock = _FakeClock(datetime(2026, 11, 4, 20, 59))
    monitor = _monitor(21, fired, clock)

    monitor._check()

    assert fired == []


def test_fires_again_next_day():
    fired = []
    clock = _FakeClock(datetime(2026, 11, 4, 22, 0))
    monitor = _monitor(21, fired, clock)
    monitor._check()

    clock.now = datetime(2026, 11, 5, 21, 1)
    monitor._check()

    assert len(fired) == 2  # 跨天复位，第二天再触发


def test_worker_emits_tip_only_when_rainy(monkeypatch):
    class _Backend:
        def __init__(self, tip):
            self._tip = tip

        def get_tomorrow_weather(self, city):
            return {"rain": bool(self._tip), "tip": self._tip}

    rainy = WeatherTipWorker(_Backend("明天有小雨，记得带伞"), "北京")
    tips = []
    rainy.tip.connect(tips.append)
    rainy.run()
    rainy.wait()
    assert tips == ["明天有小雨，记得带伞"]

    dry = WeatherTipWorker(_Backend(""), "北京")
    tips2 = []
    dry.tip.connect(tips2.append)
    dry.run()
    dry.wait()
    assert tips2 == []


def test_worker_failure_is_silent(monkeypatch):
    class _Boom:
        def get_tomorrow_weather(self, city):
            raise RuntimeError("boom")

    worker = WeatherTipWorker(_Boom(), "北京")
    tips = []
    errors = []
    worker.tip.connect(tips.append)
    worker.failed.connect(errors.append)
    worker.run()
    worker.wait()

    assert tips == []
    assert "boom" in errors[0]


def test_fired_state_survives_restart(tmp_path):
    """重启桌宠后同一晚不应再弹一次。"""
    state = tmp_path / "weather-tip.json"
    fired = []
    clock = _FakeClock(datetime(2026, 11, 4, 21, 5))

    first = WeatherTipMonitor(21, state_path=state, clock=clock)
    first.check_due.connect(lambda: fired.append(1))
    first._check()

    second = WeatherTipMonitor(21, state_path=state, clock=clock)
    second.check_due.connect(lambda: fired.append(1))
    second._check()

    assert len(fired) == 1
    assert state.exists()


def test_state_file_next_day_fires_again(tmp_path):
    state = tmp_path / "weather-tip.json"
    fired = []
    clock = _FakeClock(datetime(2026, 11, 4, 21, 5))
    WeatherTipMonitor(21, state_path=state, clock=clock)._check()

    clock.now = datetime(2026, 11, 5, 21, 5)
    monitor = WeatherTipMonitor(21, state_path=state, clock=clock)
    monitor.check_due.connect(lambda: fired.append(1))
    monitor._check()

    assert len(fired) == 1


def test_corrupt_state_file_does_not_block(tmp_path):
    state = tmp_path / "weather-tip.json"
    state.write_text("{ not json", encoding="utf-8")
    fired = []
    monitor = WeatherTipMonitor(
        21, state_path=state, clock=_FakeClock(datetime(2026, 11, 4, 21, 5))
    )
    monitor.check_due.connect(lambda: fired.append(1))

    monitor._check()

    assert len(fired) == 1


def test_client_omits_city_when_empty(monkeypatch):
    """城市留空时不传 query，由后端用 WEATHER_TIP_CITY。"""
    import pet.backend_client as module

    seen = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"rain": False}

    monkeypatch.setattr(
        module.httpx,
        "request",
        lambda method, url, **kw: (seen.update(url=url), _Resp())[1],
    )
    client = module.BackendClient("http://x", "key")

    client.get_tomorrow_weather("")
    assert seen["url"].endswith("/api/weather/tomorrow")

    client.get_tomorrow_weather("北京")
    assert "city=%E5%8C%97%E4%BA%AC" in seen["url"]
