"""B7 文本解析扩展（成员 C 提出、供 B 评审）：多日期/多时刻子句、晚间语境与相对时间。

原契约测试见 test_b7_drafts.py；本文件只覆盖新增行为，全部基于固定参考时刻。
"""

import asyncio

from app.task_parse import TextInput, parse_tasks

BASE_REF = "2026-11-01T12:00:00+08:00"
TZ = "Asia/Shanghai"


def parse(text):
    payload = TextInput(text=text, reference_at=BASE_REF, timezone=TZ)
    return asyncio.run(parse_tasks(payload))["drafts"]


def test_comma_due_clause_merges_into_one_draft():
    """「明天下午3点提醒我交实验报告，下周五前交报告」→ 同一事项一张草稿。"""
    (item,) = parse("明天下午3点提醒我交实验报告，下周五前交报告")
    assert item["title"] == "交实验报告"
    assert item["remind_at"] == "2026-11-02T15:00:00+08:00"
    assert item["due_at"] == "2026-11-06"
    assert item["needs_confirmation"] == []


def test_second_clock_for_due_does_not_flag_remind_unknown():
    """「明天下午3点提醒我交实验报告，4点截止」→ 提醒用第一个时刻，截止只有日期。"""
    (item,) = parse("明天下午3点提醒我交实验报告，4点截止")
    assert item["title"] == "交实验报告"
    assert item["remind_at"] == "2026-11-02T15:00:00+08:00"
    assert item["due_at"] == "2026-11-02"
    assert item["needs_confirmation"] == []


def test_evening_bare_clock_and_relative_offset():
    """「今晚六点吃饭，吃完饭15分钟后提醒我吃药」→ 吃饭 18:00，吃药 18:15。"""
    first, second = parse("今晚六点吃饭，吃完饭15分钟后提醒我吃药")
    assert first["title"] == "吃饭"
    assert first["remind_at"] is None  # 未说提醒：只标「仅有时刻」
    assert "time" in first["needs_confirmation"]
    assert second["title"] == "吃药"
    assert second["remind_at"] == "2026-11-01T18:15:00+08:00"
    assert second["needs_confirmation"] == []


def test_relative_offset_without_anchor_uses_reference_time():
    (item,) = parse("30分钟后提醒我交作业")
    assert item["title"] == "交作业"
    assert item["remind_at"] == "2026-11-01T12:30:00+08:00"
    assert "date" not in item["needs_confirmation"]


def test_hours_and_half_hour_offsets():
    (item,) = parse("两小时后提醒我交作业")
    assert item["remind_at"] == "2026-11-01T14:00:00+08:00"
    (half,) = parse("半小时后提醒我吃药")
    assert half["remind_at"] == "2026-11-01T12:30:00+08:00"


def test_independent_comma_clauses_still_split():
    first, second = parse("明天下午三点提醒我交报告，后天上午九点提醒我开会")
    assert first["remind_at"] == "2026-11-02T15:00:00+08:00"
    assert second["remind_at"] == "2026-11-03T09:00:00+08:00"
