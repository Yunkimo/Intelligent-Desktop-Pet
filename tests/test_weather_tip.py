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
