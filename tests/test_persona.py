"""persona 系统提示词测试。"""

from datetime import datetime

from pet.config import Settings
from pet.persona import build_system_prompt


def test_prompt_contains_identity():
    s = Settings()
    prompt = build_system_prompt(s)
    assert s.pet_name in prompt
    assert s.personality in prompt
    assert s.tone in prompt


def test_prompt_explains_schedule_vs_reminder():
    prompt = build_system_prompt(Settings())
    assert "create_task" in prompt
    assert "create_reminder" in prompt
    assert "打勾" in prompt  # 有完成语义的记日程
    assert "小程序" in prompt


def test_prompt_includes_current_time():
    now = datetime(2026, 11, 6, 15, 30)
    prompt = build_system_prompt(Settings(), now=now)
    weekday = "一二三四五六日"[now.weekday()]
    assert "2026-11-06 15:30" in prompt
    assert f"周{weekday}" in prompt
