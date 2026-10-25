"""真实 HTTP/TLS/WS、启停、持久化与恢复；不替代公网或微信真机。"""

import datetime as dt
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pytest
from backup_backend_db import backup_database
from check_deployment import endpoints, exercise_deployment
from conftest import ROOT, free_port, run, service
from websockets.sync.client import connect


@pytest.mark.parametrize("tls", [False, True])
def test_real_readonly_check(tmp_path, isolated_env, tls_files, tls):
    """HTTP 与受信 CA 的 HTTPS 均须七项通过，TLS 错误不能算拒绝。"""
    with service(tmp_path, isolated_env, tls=tls_files if tls else None) as (base, _):
        args = [sys.executable, ROOT / "scripts/check_deployment.py", base]
        if tls:
            untrusted = run(args, isolated_env)
            assert untrusted.returncode != 0
            assert "PASS WS" not in untrusted.stdout
            args += ["--ca-file", tls_files[0]]
        result = run(args, isolated_env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "7/7" in result.stdout
        assert isolated_env["API_TOKEN"] not in result.stdout + result.stderr


@pytest.mark.parametrize("tls", [False, True])
def test_business_check_and_cleanup(tmp_path, isolated_env, tls_files, tls):
    """真实服务验证业务写入、两类事件、重连；清理后业务库为空。"""
    with service(tmp_path, isolated_env, tls=tls_files if tls else None) as (base, _):
        args = [sys.executable, ROOT / "scripts/check_deployment.py", base, "--exercise"]
        if tls:
            args += ["--ca-file", tls_files[0]]
        result = run(args, isolated_env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "14/14" in result.stdout
        assert isolated_env["API_TOKEN"] not in result.stdout + result.stderr
        import ssl

        verify = ssl.create_default_context(cafile=str(tls_files[0])) if tls else True
        with httpx.Client(
            base_url=base,
            headers={"X-API-Key": isolated_env["API_TOKEN"]},
            trust_env=False,
            verify=verify,
        ) as client:
            assert client.get("/api/tasks").json() == []
            assert client.get("/api/courses").json() == []


def test_event_failure_still_cleans_only_owned_data(tmp_path, isolated_env, monkeypatch, capsys):
    """事件缺失必须失败；已落库的本轮记录被清理，其他数据保持不变。"""
    import check_deployment

    real_connect = check_deployment.connect

    class MissingEvents:
        def recv(self, timeout):
            raise TimeoutError("测试中丢弃事件")

    @contextmanager
    def missing_events(*args, **kwargs):
        with real_connect(*args, **kwargs):
            yield MissingEvents()

    with service(tmp_path, isolated_env) as (base, _):
        headers = {"X-API-Key": isolated_env["API_TOKEN"]}
        seed = httpx.post(
            base + "/api/tasks", headers=headers, json={"title": "保留原数据"}, trust_env=False
        ).json()
        monkeypatch.setattr(check_deployment, "connect", missing_events)
        results = exercise_deployment(base, isolated_env["API_TOKEN"])
        assert not all(ok for _, ok in results)
        assert httpx.get(base + "/api/tasks", headers=headers, trust_env=False).json() == [seed]
        assert isolated_env["API_TOKEN"] not in capsys.readouterr().out


def test_network_failure_is_not_auth_success(tmp_path, isolated_env):
    """端口不通时七项都失败，不能用任意异常冒充鉴权成功。"""
    result = run(
        [sys.executable, ROOT / "scripts/check_deployment.py", f"http://127.0.0.1:{free_port()}"],
        isolated_env,
    )
    assert result.returncode == 1
    assert "0/7" in result.stdout
    assert "PASS" not in result.stdout
    assert isolated_env["API_TOKEN"] not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "url", ["ftp://host", "https://host?token=abc", "https://a:b@host", "http://host:abc"]
)
def test_bad_entry_rejected(url):
    """无效地址和含凭据地址在发请求前被拒绝。"""
    with pytest.raises(ValueError):
        endpoints(url)


def test_prefix_and_ipv6():
    """派生协议时保留路径前缀与 IPv6 地址。"""
    assert endpoints("https://[::1]:8443/idp/") == (
        "https://[::1]:8443/idp",
        "wss://[::1]:8443/idp",
    )


def test_business_restart_backup_restore(tmp_path, isolated_env):
    """真实写入/事件/重连、单条 PC 提醒、重启持久化及恢复数据一致性。"""
    headers = {"X-API-Key": isolated_env["API_TOKEN"]}
    with service(tmp_path, isolated_env) as (base, _):
        ws_url = (
            base.replace("http:", "ws:") + "/ws?" + urlencode({"token": isolated_env["API_TOKEN"]})
        )
        with httpx.Client(base_url=base, headers=headers, trust_env=False) as client:
            with connect(ws_url, proxy=None) as ws:
                created = client.post("/api/tasks", json={"title": "C4 临时持久化验证"})
                assert created.status_code == 201
                task_id = created.json()["id"]
                event = json.loads(ws.recv(timeout=5))
                assert event["type"] == "task.created" and event["data"]["id"] == task_id
            # 真实断开后重连，再读取服务器当前状态。
            with connect(ws_url, proxy=None) as ws:
                assert any(row["id"] == task_id for row in client.get("/api/tasks").json())
                due = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)
                reminder = client.post(
                    "/api/reminders",
                    json={
                        "title": "C4 临时 PC 提醒",
                        "remind_at": due.isoformat(),
                        "channel": "pc",
                    },
                )
                assert reminder.status_code == 201
                event = json.loads(ws.recv(timeout=5))
                assert event["type"] == "reminder.due"
                assert (dt.datetime.now(dt.timezone.utc) - due).total_seconds() <= 5
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(mode=0o700)
    backup = backup_dir / "before-update.db"
    backup_database(Path(isolated_env["DB_PATH"]), backup)
    with service(tmp_path, isolated_env) as (base, _):
        with httpx.Client(base_url=base, headers=headers, trust_env=False) as client:
            assert any(row["id"] == task_id for row in client.get("/api/tasks").json())
            new = client.post("/api/tasks", json={"title": "备份后的写入"}).json()["id"]
    restored = tmp_path / "restored.db"
    backup_database(backup, restored)
    with service(tmp_path, dict(isolated_env, DB_PATH=str(restored))) as (base, _):
        tasks = httpx.get(base + "/api/tasks", headers=headers, trust_env=False).json()
        assert task_id in {row["id"] for row in tasks}
        assert new not in {row["id"] for row in tasks}
