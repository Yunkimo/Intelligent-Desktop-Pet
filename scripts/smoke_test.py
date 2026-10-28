"""冒烟测试：不启动 GUI，分别验证 LLM / TTS 连通性。

用法：python scripts/smoke_test.py [llm|tts]
默认都测。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pet.config import Settings  # noqa: E402
from pet.llm import LLMClient  # noqa: E402
from pet.providers import create_chat_provider  # noqa: E402
from pet.tts import TTSEngine  # noqa: E402


def test_llm(settings: Settings) -> None:
    if not settings.llm_api_key:
        print("[LLM] 跳过：未配置 LLM_API_KEY")
        return
    client = LLMClient(create_chat_provider(settings))
    print(f"[LLM] 调用 {settings.llm_model} @ {settings.llm_base_url} …")
    reply = client.chat([{"role": "user", "content": "你好，用一句话打个招呼"}])
    print(f"[LLM] OK: {reply}")


def test_tts(settings: Settings) -> None:
    eng = TTSEngine(settings.tts_voice, settings.tts_rate, settings.tts_pitch)
    print(f"[TTS] 合成音色 {settings.tts_voice} …")
    path = eng.synthesize("你好呀，我是你的桌面小宠物！")
    print(f"[TTS] OK: {path}")


if __name__ == "__main__":
    s = Settings()
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("llm", "all"):
        test_llm(s)
    if which in ("tts", "all"):
        test_tts(s)
