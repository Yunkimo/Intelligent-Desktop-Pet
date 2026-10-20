"""入口脚本测试：无控制台启动时把异常追加写入日志。"""

import main


def test_log_startup_error_appends_traceback(tmp_path, monkeypatch):
    log_path = tmp_path / "data" / "pet-error.log"
    monkeypatch.setattr(main, "_ERROR_LOG", log_path)

    try:
        raise RuntimeError("启动失败")
    except RuntimeError:
        main._log_startup_error()

    text = log_path.read_text(encoding="utf-8")
    assert "Traceback" in text
    assert "RuntimeError: 启动失败" in text
