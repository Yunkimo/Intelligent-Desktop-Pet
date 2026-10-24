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


def save_env_values(**values: str) -> Path:
    """把键值合并写入 .env：保留注释与既有顺序，同名键原地替换，缺失则追加。

    .env 被 .gitignore 排除，因此可以安全地存密钥；config.json 会被提交，不能存。
    返回写入的文件路径，便于调用方提示。
    """
    path = BASE_DIR / ".env"
    try:
        original = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        original = []

    pending = dict(values)
    lines: list[str] = []
    for line in original:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in pending:
                lines.append(f"{key}={pending.pop(key)}")
                continue
        lines.append(line)
    for key, value in pending.items():
        lines.append(f"{key}={value}")

    tmp = path.with_suffix(".env.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


class Settings:
    """应用配置的统一入口，各模块从这里取值。"""

    def __init__(self) -> None:
        load_dotenv(BASE_DIR / ".env")

        # —— 来自 .env 的密钥/模型配置 ——
        self.llm_api_key: str = os.getenv("LLM_API_KEY", "").strip()
        self.llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip()
        self.llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat").strip()

        # 账户余额查询用的独立凭据；留空时回退到推理用的 key 与地址
        self.account_api_key: str = os.getenv("ACCOUNT_API_KEY", "").strip() or self.llm_api_key
        self.account_base_url: str = os.getenv("ACCOUNT_BASE_URL", "").strip() or self.llm_base_url

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

        # Claude Code 回合状态监控（默认关闭，右键菜单可开）
        self.monitor_claude: bool = bool(data.get("monitor_claude", False))
        # Codex 回合状态监控（默认关闭，独立于 Claude）
        self.monitor_codex: bool = bool(data.get("monitor_codex", False))
        # 状态角标显隐（默认显示；关闭后监控照常运行，只是不弹角标）
        self.status_badges_visible: bool = bool(data.get("status_badges_visible", True))

        # 系统托盘：关闭后右键「隐藏至托盘」置灰，关闭窗口仍直接退出
        self.tray_enabled: bool = bool(data.get("tray_enabled", True))

        # Token 用量：本地记账文件与按天明细保留天数（总计不受裁剪影响）
        self.usage_retention_days: int = self._bounded_int(
            data.get("usage_retention_days", 90), "usage_retention_days", 1, 3650
        )
        # 余额查询超时（秒）。实测部分网络下 DeepSeek 余额接口要 8 秒才返回，
        # 默认 10 秒；上限 30 秒，避免 UI 侧无限等待
        self.balance_timeout_seconds: float = self._bounded_float(
            data.get("balance_timeout_seconds", 10), "balance_timeout_seconds", 0.5, 30
        )
        # 桌宠右下角的用量入口图标（相对 assets_dir）
        self.rice_icon: str = data.get("rice_icon", "Rice.png")
        # 「跳转至 API 网站」的目标地址；留空则按 API 地址推出站点根
        self.api_website: str = str(data.get("api_website", "")).strip()

        # 路径统一解析为绝对路径
        self.assets_dir: Path = BASE_DIR / data.get("assets_dir", "assets")
        self.history_path: Path = BASE_DIR / data.get("history_path", "data/history.json")
        self.agent_status_path: Path = BASE_DIR / data.get(
            "agent_status_path", "data/agent-status.json"
        )
        self.usage_path: Path = BASE_DIR / data.get("usage_path", "data/usage.json")

    @staticmethod
    def _bounded_int(value: object, name: str, low: int, high: int) -> int:
        """读取整数配置并夹在 [low, high]；非法值直接报错，避免静默用错口径。"""
        try:
            number = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 必须是整数：{value!r}") from exc
        if not low <= number <= high:
            raise ValueError(f"{name} 必须在 {low}-{high} 之间：{number}")
        return number

    @staticmethod
    def _bounded_float(value: object, name: str, low: float, high: float) -> float:
        """读取浮点配置并夹在 [low, high]；非法值直接报错。"""
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 必须是数字：{value!r}") from exc
        if not low <= number <= high:
            raise ValueError(f"{name} 必须在 {low}-{high} 之间：{number}")
        return number

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

    def update_monitor_claude(self, enabled: bool) -> None:
        """更新 Claude Code 状态监控开关并写回 config.json。"""
        self.monitor_claude = bool(enabled)
        self._save_json(monitor_claude=self.monitor_claude)

    def update_monitor_codex(self, enabled: bool) -> None:
        """更新 Codex 状态监控开关并写回 config.json。"""
        self.monitor_codex = bool(enabled)
        self._save_json(monitor_codex=self.monitor_codex)

    def update_status_badges_visible(self, visible: bool) -> None:
        """更新状态角标显隐开关并写回 config.json。"""
        self.status_badges_visible = bool(visible)
        self._save_json(status_badges_visible=self.status_badges_visible)

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
