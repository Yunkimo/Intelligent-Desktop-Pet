"""配置加载：合并 .env（密钥）与 config.json（非敏感配置）。"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .paths import app_dir

# 项目根目录（pet/ 的上一级）
BASE_DIR = app_dir()
DEFAULT_TTS_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_TTS_TIMEOUT_SECONDS = 30


class Settings:
    """应用配置的统一入口，各模块从这里取值。"""

    def __init__(self) -> None:
        load_dotenv(BASE_DIR / ".env")

        # —— 来自 .env 的密钥/模型配置 ——
        self.llm_api_key: str = os.getenv("LLM_API_KEY", "").strip()
        self.llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip()
        self.llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat").strip()

        # —— 后端服务配置（API_TOKEN 是后端侧密钥，桌宠端填同一值以通过 X-API-Key 鉴权）——
        self.backend_url: str = os.getenv("BACKEND_URL", "http://127.0.0.1:8001").strip()
        self.api_token: str = os.getenv("API_TOKEN", "").strip()

        # —— 来自 config.json 的非敏感配置 ——
        self._load_json()

    def _load_json(self) -> None:
        path = BASE_DIR / "config.json"
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        self.pet_name: str = data.get("pet_name", "小萌")
        persona = data.get("persona", {})
        self.personality: str = persona.get("personality", "活泼可爱")
        self.tone: str = persona.get("tone", "口语化、简短俏皮")
        self.personas: dict[str, dict] = data.get("personas", {})

        # LLM 生成参数（非敏感，默认保持现有行为）
        self.llm_temperature: float = float(data.get("llm_temperature", 0.9))
        self.llm_max_tokens: int = int(data.get("llm_max_tokens", 1024))

        self.frames: list[str] = data.get("frames", [])
        self.sprite_size: int = int(data.get("sprite_size", 180))

        self.whisper_model: str = data.get("whisper_model", "base")
        self.tts_voice: str = data.get("tts_voice", DEFAULT_TTS_VOICE)
        # 旧默认声音已不在服务声音列表中，仅迁移该旧值，保留其他自选声音。
        if self.tts_voice == "zh-CN-XiaoyouNeural":
            self.tts_voice = DEFAULT_TTS_VOICE
        self.tts_timeout_seconds = float(
            data.get("tts_timeout_seconds", DEFAULT_TTS_TIMEOUT_SECONDS)
        )
        if not 0 < self.tts_timeout_seconds <= 120:
            raise ValueError("tts_timeout_seconds 必须大于 0 且不超过 120 秒")
        self.tts_rate: str = data.get("tts_rate", "+10%")
        self.tts_windows_fallback = bool(data.get("tts_windows_fallback", True))
        self.tts_pitch: str = data.get("tts_pitch", "+20Hz")
        self.enable_voice: bool = bool(data.get("enable_voice", True))
        # 全局语音快捷键：长按开始录音、松开停止并识别（默认 Ctrl+T）
        self.voice_hotkey: str = data.get("voice_hotkey", "ctrl+t")

        self.max_history: int = int(data.get("max_history", 20))
        self.max_record_secs: float = float(data.get("max_record_secs", 15))
        self.bubble_timeout_ms: int = int(data.get("bubble_timeout_ms", 8000))
        self.persist_history: bool = bool(data.get("persist_history", True))

        # 健康关怀：久坐检测开关与提醒间隔（分钟）
        self.health_enabled: bool = bool(data.get("health_enabled", True))
        self.sedentary_interval_min: int = int(data.get("sedentary_interval_min", 45))

        # 路径统一解析为绝对路径
        self.assets_dir: Path = BASE_DIR / data.get("assets_dir", "assets")
        self.history_path: Path = BASE_DIR / data.get("history_path", "data/history.json")

    def _save_json(self, **updates: object) -> None:
        """把给定字段合并写回 config.json，保留其余字段。"""
        path = BASE_DIR / "config.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data.update(updates)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def update_frames(self, frames: list[str]) -> None:
        """更新形象帧列表并写回 config.json，使更换在重启后仍然生效。"""
        self.frames = frames
        self._save_json(frames=frames)

    def update_voice_hotkey(self, hotkey: str) -> None:
        """更新语音快捷键并写回 config.json，使设置重启后仍然生效。"""
        self.voice_hotkey = hotkey
        self._save_json(voice_hotkey=hotkey)

    def update_health(self, enabled: bool | None = None, sedentary_min: int | None = None) -> None:
        """更新健康关怀配置并写回 config.json（复用 _save_json）。"""
        updates: dict[str, object] = {}
        if enabled is not None:
            self.health_enabled = bool(enabled)
            updates["health_enabled"] = self.health_enabled
        if sedentary_min is not None:
            self.sedentary_interval_min = int(sedentary_min)
            updates["sedentary_interval_min"] = self.sedentary_interval_min
        self._save_json(**updates)

    def switch_persona(self, name: str) -> bool:
        """切换到指定人设（从 personas 预设读取），写回 config.json 并返回是否成功。"""
        preset = self.personas.get(name)
        if not preset:
            return False
        self.pet_name = name
        self.personality = preset.get("personality", self.personality)
        self.tone = preset.get("tone", self.tone)
        self._save_json(
            pet_name=self.pet_name,
            persona={"personality": self.personality, "tone": self.tone},
        )
        return True

    def add_persona(self, name: str, personality: str, tone: str) -> bool:
        """新增（或覆盖）一个人设预设，写回 config.json 并返回是否成功。"""
        name = name.strip()
        if not name:
            return False
        self.personas[name] = {"personality": personality, "tone": tone}
        self._save_json(personas=self.personas)
        return True
