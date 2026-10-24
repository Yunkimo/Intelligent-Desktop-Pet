"""本地用量记账测试：usage 归一化、按天聚合、裁剪、容错与并发。"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from pet.usage import Totals, UsageStore, normalize_usage

_PEAK = datetime(2026, 10, 26, 10, 0)  # 周一高峰


def _usage(prompt=1000, completion=200, hit=None, cached=None):
    """构造一个 usage 伪对象，字段可按需缺省。"""
    data = {}
    if prompt is not None:
        data["prompt_tokens"] = prompt
    if completion is not None:
        data["completion_tokens"] = completion
    if hit is not None:
        data["prompt_cache_hit_tokens"] = hit
    if cached is not None:
        data["prompt_tokens_details"] = SimpleNamespace(cached_tokens=cached)
    return SimpleNamespace(**data)


# ---------- 归一化 ----------
def test_normalize_prefers_deepseek_cache_fields():
    assert normalize_usage(_usage(1000, 200, hit=400)) == (1000, 200, 400)


def test_normalize_falls_back_to_standard_cached_tokens():
    assert normalize_usage(_usage(1000, 200, cached=250)) == (1000, 200, 250)


def test_normalize_without_cache_fields_counts_all_as_miss():
    assert normalize_usage(_usage(1000, 200)) == (1000, 200, 0)


def test_normalize_rejects_usage_without_prompt_tokens():
    assert normalize_usage(SimpleNamespace(completion_tokens=10)) is None
    assert normalize_usage(None) is None


def test_normalize_clamps_cached_to_prompt():
    assert normalize_usage(_usage(100, 10, hit=500)) == (100, 10, 100)


# ---------- 记账 ----------
def test_record_accumulates_today_and_total(tmp_path):
    store = UsageStore(tmp_path / "usage.json")
    store.record_usage(_usage(1000, 200, hit=400), "deepseek-chat", at=_PEAK)
    store.record_usage(_usage(500, 50), "deepseek-chat", at=_PEAK)

    snap = store.snapshot(now=_PEAK)
    assert snap["today"].requests == 2
    assert snap["today"].prompt == 1500
    assert snap["today"].completion == 250
    assert snap["today"].cached == 400
    assert snap["total"].requests == 2
    assert snap["total"].cost_cny > 0


def test_record_with_unknown_model_tracks_unpriced_tokens(tmp_path):
    store = UsageStore(tmp_path / "usage.json")
    store.record_usage(_usage(100, 20), "unknown-model", at=_PEAK)

    snap = store.snapshot(now=_PEAK)
    assert snap["total"].requests == 1
    assert snap["total"].unpriced == 120
    assert snap["total"].cost_cny == 0


def test_invalid_usage_is_ignored(tmp_path):
    store = UsageStore(tmp_path / "usage.json")
    store.record_usage(None, "deepseek-chat", at=_PEAK)
    assert store.snapshot(now=_PEAK)["total"].requests == 0


def test_snapshot_seven_day_window_includes_today_only(tmp_path):
    store = UsageStore(tmp_path / "usage.json")
    store.record_usage(_usage(10, 1), "deepseek-chat", at=_PEAK - timedelta(days=6))
    store.record_usage(_usage(100, 10), "deepseek-chat", at=_PEAK - timedelta(days=7))
    store.record_usage(_usage(1000, 100), "deepseek-chat", at=_PEAK)

    snap = store.snapshot(now=_PEAK)
    # 近 7 天含今天与前 6 天，不含第 7 天前
    assert snap["last_7_days"].prompt == 1010
    assert snap["total"].prompt == 1110


def test_retention_trims_days_but_keeps_total(tmp_path):
    path = tmp_path / "usage.json"
    store = UsageStore(path, retention_days=2)
    old = _PEAK - timedelta(days=10)
    store.record_usage(_usage(100, 10), "deepseek-chat", at=old)
    store.record_usage(_usage(1000, 100), "deepseek-chat", at=_PEAK)

    snap = store.snapshot(now=_PEAK)
    assert [key for key, _ in snap["days"]] == [_PEAK.date().isoformat()]
    assert snap["total"].prompt == 1100


def test_corrupt_file_recovers_without_raising(tmp_path):
    path = tmp_path / "usage.json"
    path.write_text("{ this is not json", encoding="utf-8")

    store = UsageStore(path)
    assert store.load_error is not None
    store.record_usage(_usage(10, 1), "deepseek-chat", at=_PEAK)
    assert store.snapshot(now=_PEAK)["total"].requests == 1


def test_persisted_file_is_reloaded(tmp_path):
    path = tmp_path / "usage.json"
    first = UsageStore(path)
    first.record_usage(_usage(1000, 200, hit=100), "deepseek-chat", at=_PEAK)

    second = UsageStore(path)
    snap = second.snapshot(now=_PEAK)
    assert snap["total"].requests == 1
    assert snap["total"].cached == 100
    assert snap["total"].cost_cny == first.snapshot(now=_PEAK)["total"].cost_cny


def test_cost_survives_round_trip_as_string(tmp_path):
    path = tmp_path / "usage.json"
    store = UsageStore(path)
    store.record_usage(_usage(1000, 200), "deepseek-chat", at=_PEAK)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw["total"]["cost_cny"], str)
    assert Decimal(raw["total"]["cost_cny"]) > 0


def test_concurrent_records_are_not_lost(tmp_path):
    store = UsageStore(tmp_path / "usage.json")

    def record(_index: int) -> None:
        store.record_usage(_usage(10, 1), "deepseek-chat", at=_PEAK)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(record, range(100)))

    assert store.snapshot(now=_PEAK)["total"].requests == 100


def test_totals_merge_sums_every_field():
    left = Totals(1, 2, 3, 4, Decimal("0.5"), 6)
    right = Totals(10, 20, 30, 40, Decimal("0.25"), 60)
    left.merge(right)
    assert left.to_dict() == {
        "prompt": 11,
        "completion": 22,
        "cached": 33,
        "requests": 44,
        "cost_cny": "0.75",
        "unpriced": 66,
    }
