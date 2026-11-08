"""选择提示在异步确认和普通气泡提示期间保持可见。"""

from unittest.mock import Mock

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from pet.config import Settings
from pet.window import PetWindow


def test_capture_question_waits_for_valid_choice(qapp, monkeypatch, tmp_path):
    settings = Settings()
    settings.enable_voice = False
    settings.health_enabled = False
    settings.tray_enabled = False
    settings.weather_tip_enabled = False
    settings.habits_enabled = False
    settings.monitor_claude = False
    settings.monitor_codex = False
    settings.persist_history = False
    settings.history_path = tmp_path / "history.json"
    settings.usage_path = tmp_path / "usage.json"
    settings.bubble_timeout_ms = 20

    monkeypatch.setattr("pet.window.AccountStore.load", lambda self: None)
    monkeypatch.setattr(PetWindow, "_init_hotkey", lambda self: setattr(self, "hotkey", None))
    window = PetWindow(settings)

    def prompt(message, stage):
        return {
            "status": "needs_clarification",
            "message": message,
            "stage": stage,
            "request_id": "test-request",
            "choices": [{"label": "选项一"}, {"label": "选项二"}],
        }

    capture = Mock(return_value=prompt("请选择时间", "item"))
    confirm = Mock(
        side_effect=[
            RuntimeError("暂时无法确认"),
            prompt("请选择提醒时间", "reminder"),
            {"status": "created", "message": "已添加待办"},
        ]
    )
    monkeypatch.setattr(window.backend, "capture_text", capture)
    monkeypatch.setattr(window.backend, "confirm_capture", confirm)
    window.backend.session_token = "test-session"

    def submit(text):
        window.input.edit.setText(text)
        QTest.keyClick(window.input.edit, Qt.Key.Key_Return)
        assert window.chat_worker.wait(2000)
        qapp.processEvents()

    try:
        window.show()
        window.input.show()
        submit("明天三点交报告")
        QTest.qWait(60)
        assert window.bubble.isVisible()
        assert window.input.isVisible() and window.input.edit.isEnabled()
        assert "请选择时间" in "".join(window.bubble._wrap())

        window.show_hint("事项已同步")
        submit("9")
        assert "请选择时间" in "".join(window.bubble._wrap())
        assert "可选的序号" in "".join(window.bubble._wrap())
        assert confirm.call_count == 0
        assert capture.call_count == 1

        submit("1")
        assert window.input.isVisible()
        assert "暂时无法确认" in "".join(window.bubble._wrap())
        assert "请选择时间" in "".join(window.bubble._wrap())

        submit("1")
        assert window.input.isVisible()
        assert "请选择提醒时间" in "".join(window.bubble._wrap())

        submit("1")
        assert not window.input.isVisible()
        assert "已添加待办" in "".join(window.bubble._wrap())
        assert "请选择提醒时间" not in "".join(window.bubble._wrap())
        QTest.qWait(60)
        assert not window.bubble.isVisible()

        capture.return_value = {"status": "needs_clarification", "message": "请补充开始时间"}
        window.input.show()
        submit("安排开会")
        assert window.input.isVisible() and window.input.edit.isEnabled()
        assert "请补充开始时间" in "".join(window.bubble._wrap())
    finally:
        window.close()
