"""Claude Code 状态监控测试：状态文件解析与轮询信号。"""

import json
import time

from pet.agent_status import AgentStatusMonitor, read_status


def _write(path, state: str, ts: float | None = None, event: str = "Stop") -> None:
    path.write_text(
        json.dumps(
            {
                "state": state,
                "event": event,
                "session_id": "s1",
                "ts": time.time() if ts is None else ts,
            }
        ),
        encoding="utf-8",
    )


def test_read_status_valid(tmp_path):
    path = tmp_path / "status.json"
    _write(path, "working")
    info = read_status(path)
    assert info is not None
    assert info["state"] == "working"
    assert info["event"] == "Stop"


def test_read_status_rejects_invalid(tmp_path):
    path = tmp_path / "status.json"
    path.write_text("not json", encoding="utf-8")
    assert read_status(path) is None
    path.write_text(json.dumps({"state": "sleeping"}), encoding="utf-8")
    assert read_status(path) is None


def test_monitor_emits_only_on_change(qapp, tmp_path):
    path = tmp_path / "status.json"
    monitor = AgentStatusMonitor(path)
    seen: list[str] = []
    monitor.state_changed.connect(seen.append)

    monitor.poll()  # 文件不存在 → idle
    _write(path, "working")
    monitor.poll()
    monitor.poll()  # 状态未变，不重复发信号
    _write(path, "done")
    monitor.poll()

    assert seen == ["idle", "working", "done"]


def test_monitor_marks_stale_working_as_unknown(qapp, tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    _write(path, "working", ts=1.0)
    monkeypatch.setattr("pet.agent_status.time.time", lambda: 1000.0)
    monitor = AgentStatusMonitor(path, stale_seconds=300)
    seen: list[str] = []
    monitor.state_changed.connect(seen.append)

    monitor.poll()

    assert seen == ["unknown"]


def test_monitor_restart_reemits_current_state(qapp, tmp_path):
    path = tmp_path / "status.json"
    _write(path, "working")
    monitor = AgentStatusMonitor(path)
    seen: list[str] = []
    monitor.state_changed.connect(seen.append)

    monitor.start()
    monitor.stop()
    monitor.start()  # 重新开启监控时应再发一次当前状态
    monitor.stop()

    assert seen == ["working", "working"]


def test_monitor_missing_file_after_working_becomes_unknown(qapp, tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    _write(path, "working", ts=1.0)
    monkeypatch.setattr("pet.agent_status.time.time", lambda: 100.0)
    monitor = AgentStatusMonitor(path, stale_seconds=300)
    seen: list[str] = []
    monitor.state_changed.connect(seen.append)

    monitor.poll()
    assert seen == ["working"]

    path.unlink()
    monkeypatch.setattr("pet.agent_status.time.time", lambda: 1000.0)
    monitor.poll()
    assert seen == ["working", "unknown"]


def test_monitor_keeps_stale_done(qapp, tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    _write(path, "done", ts=1.0)
    monkeypatch.setattr("pet.agent_status.time.time", lambda: 1000.0)
    monitor = AgentStatusMonitor(path, stale_seconds=300)
    seen: list[str] = []
    monitor.state_changed.connect(seen.append)

    monitor.poll()

    assert seen == ["done"]


def test_read_status_accepts_millisecond_timestamp(tmp_path):
    path = tmp_path / "status.json"
    _write(path, "done", ts=1_700_000_000_000)
    info = read_status(path)
    assert info is not None
    assert info["ts"] == 1_700_000_000.0
