"""时延验收必须保留整秒 Date 与网络往返的不确定性，不能直接相减。"""

from email.utils import formatdate
from unittest.mock import Mock

import check_cloud_reminder_latency as latency
import httpx
import pytest


def test_date_bounds_include_server_clock_offset(monkeypatch):
    # 服务器比电脑快 2.4s；请求跨秒且回程耗时不对称。
    starts = [100 + number * 0.23 for number in range(8)]
    times = iter(value for start in starts for value in (start, start + 0.18))
    monkeypatch.setattr(latency.time, "time", lambda: next(times))
    monkeypatch.setattr(latency.time, "sleep", lambda _: None)
    responses = iter(
        httpx.Response(
            200,
            json={"status": "ok"},
            headers={"date": formatdate(int(start + 0.03 + 2.4), usegmt=True)},
            request=httpx.Request("GET", "http://test/api/health"),
        )
        for start in starts
    )
    result = latency.clock_bounds(Mock(get=lambda *args, **kwargs: next(responses)))
    assert result["lower_seconds"] <= 2.4 <= result["upper_seconds"]
    assert 0 < result["upper_seconds"] - result["lower_seconds"] < 0.6


def test_clock_step_cannot_pass_clock_preflight(monkeypatch):
    times = iter(value for number in range(8) for value in (100 + number, 100.1 + number))
    monkeypatch.setattr(latency.time, "time", lambda: next(times))
    monkeypatch.setattr(latency.time, "sleep", lambda _: None)
    responses = iter(
        httpx.Response(
            200,
            json={"status": "ok"},
            headers={"date": formatdate(102 + number + (20 if number >= 4 else 0), usegmt=True)},
            request=httpx.Request("GET", "http://test/api/health"),
        )
        for number in range(8)
    )
    with pytest.raises(ValueError, match="inconsistent"):
        latency.clock_bounds(Mock(get=lambda *args, **kwargs: next(responses)))
