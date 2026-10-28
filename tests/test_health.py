"""HealthMonitor 久坐检测逻辑测试：注入假空闲源与假时钟，绕过真实系统 API 与 QTimer。"""

from pet.health import HealthMonitor


class _Settings:
    def __init__(self, enabled=True, sedentary_min=45) -> None:
        self.health_enabled = enabled
        self.sedentary_interval_min = sedentary_min


class _Idle:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    def idle_seconds(self) -> float:
        return self.seconds


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_due_after_sitting_threshold(qapp):
    clock = _Clock()
    mon = HealthMonitor(_Settings(sedentary_min=1), idle_source=_Idle(10), clock=clock)
    fired: list[str] = []
    mon.sedentary_due.connect(lambda: fired.append("due"))
    mon._check()  # 在座，开始计时
    clock.t = 61
    mon._check()
    assert fired == ["due"]


def test_no_reminder_when_away(qapp):
    clock = _Clock()
    mon = HealthMonitor(_Settings(sedentary_min=1), idle_source=_Idle(60), clock=clock)
    fired: list[str] = []
    mon.sedentary_due.connect(lambda: fired.append("due"))
    mon._check()
    clock.t = 120
    mon._check()
    assert fired == []  # 空闲 ≥ 1 分钟 = 离座，不算久坐


def test_repeats_every_interval(qapp):
    clock = _Clock()
    mon = HealthMonitor(_Settings(sedentary_min=1), idle_source=_Idle(10), clock=clock)
    fired: list[str] = []
    mon.sedentary_due.connect(lambda: fired.append("due"))
    mon._check()
    clock.t = 61
    mon._check()  # 第一次
    clock.t = 120
    mon._check()  # 距上次 59s，未到一个间隔
    clock.t = 121
    mon._check()  # 距上次 60s，第二次
    assert fired == ["due", "due"]


def test_away_resets_session(qapp):
    clock = _Clock()
    idle = _Idle(10)
    mon = HealthMonitor(_Settings(sedentary_min=1), idle_source=idle, clock=clock)
    fired: list[str] = []
    mon.sedentary_due.connect(lambda: fired.append("due"))
    mon._check()  # 在座，session 开始于 t=0
    clock.t = 61
    mon._check()
    assert fired == ["due"]

    idle.seconds = 60  # 离座（空闲 ≥ 1 分钟）
    mon._check()

    idle.seconds = 10  # 回来，重新计时
    clock.t = 62
    mon._check()
    clock.t = 123
    mon._check()
    assert fired == ["due", "due"]


def test_idle_just_under_away_threshold_still_sitting(qapp):
    # 空闲 59 秒（< 1 分钟）仍是「在座」，累计时长照常触发
    clock = _Clock()
    mon = HealthMonitor(_Settings(sedentary_min=1), idle_source=_Idle(59), clock=clock)
    fired: list[str] = []
    mon.sedentary_due.connect(lambda: fired.append("due"))
    mon._check()
    clock.t = 61
    mon._check()
    assert fired == ["due"]


def test_settings_health_defaults():
    from pet.config import Settings

    s = Settings()
    assert isinstance(s.health_enabled, bool)
    assert s.sedentary_interval_min > 0
