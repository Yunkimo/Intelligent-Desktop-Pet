"""persona 系统提示词测试。"""

from pet.config import Settings
from pet.persona import build_system_prompt


def test_prompt_contains_identity():
    s = Settings()
    prompt = build_system_prompt(s)
    assert s.pet_name in prompt
    assert s.personality in prompt
    assert s.tone in prompt
