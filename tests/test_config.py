"""Settings 配置加载测试。"""

from pet.config import Settings


def test_defaults_when_env_unset(monkeypatch):
    for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(key, raising=False)
    s = Settings()
    assert s.llm_base_url == "https://api.deepseek.com"
    assert s.llm_model == "deepseek-chat"
    assert s.llm_api_key == ""


def test_env_override(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "my-model")
    s = Settings()
    assert s.llm_api_key == "sk-test"
    assert s.llm_base_url == "https://example.com/v1"
    assert s.llm_model == "my-model"


def test_config_json_fields():
    s = Settings()
    assert s.pet_name == "小萌"  # 运行时可通过「切换人设」更改
    assert s.whisper_model == "base"
    assert s.tts_voice == "zh-CN-XiaoxiaoNeural"
    assert s.max_history > 0


def test_llm_generation_params_defaults():
    s = Settings()
    assert s.llm_temperature == 0.9
    assert s.llm_max_tokens == 1024


def test_tray_enabled_defaults_true():
    assert Settings().tray_enabled is True


def test_update_methods_set_attrs_and_save(monkeypatch):
    saved: dict = {}
    monkeypatch.setattr(Settings, "_save_json", lambda self, **kw: saved.update(kw))
    s = Settings()
    s.update_health(enabled=False, sedentary_min=30)
    assert s.health_enabled is False
    assert s.sedentary_interval_min == 30
    assert saved == {"health_enabled": False, "sedentary_interval_min": 30}


def test_update_monitor_claude_sets_attr_and_saves(monkeypatch):
    saved: dict = {}
    monkeypatch.setattr(Settings, "_save_json", lambda self, **kw: saved.update(kw))
    s = Settings()
    s.update_monitor_claude(True)
    assert s.monitor_claude is True
    assert saved == {"monitor_claude": True}


def test_update_monitor_codex_sets_attr_and_saves(monkeypatch, tmp_path):
    import pet.config as config

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    saved: dict = {}
    monkeypatch.setattr(Settings, "_save_json", lambda self, **kw: saved.update(kw))
    s = Settings()
    assert s.monitor_codex is False
    s.update_monitor_codex(True)
    assert s.monitor_codex is True
    assert saved == {"monitor_codex": True}


def test_switch_persona_and_add_persona(monkeypatch):
    monkeypatch.setattr(Settings, "_save_json", lambda self, **kw: None)
    s = Settings()
    assert s.switch_persona("小萌") is True
    assert s.pet_name == "小萌"
    assert s.switch_persona("不存在的人设") is False
    assert s.add_persona("   ", "冷静", "简洁") is False
    assert s.add_persona("新萌", "冷静", "简洁") is True
    assert s.personas["新萌"] == {"personality": "冷静", "tone": "简洁"}


def test_legacy_voice_migrates_without_changing_custom_voice(tmp_path, monkeypatch):
    import json

    import pet.config as config

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    for original, expected in (
        ("zh-CN-XiaoyouNeural", "zh-CN-XiaoxiaoNeural"),
        ("zh-CN-YunxiNeural", "zh-CN-YunxiNeural"),
    ):
        (tmp_path / "config.json").write_text(json.dumps({"tts_voice": original}), encoding="utf-8")
        assert Settings().tts_voice == expected
        assert json.loads((tmp_path / "config.json").read_text())["tts_voice"] == original
