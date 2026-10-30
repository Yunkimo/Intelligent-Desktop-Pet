"""在临时发布目录中演练真实历史版本升级、schema 迁移与停服恢复回滚。"""

import io
import json
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import httpx
import pytest
from backup_backend_db import backup_database
from conftest import ROOT, free_port, run, service

# B2 调度的真实仓库版本，迁移版本为 1；当前应用升级到 B3 的版本 2。
PREVIOUS_REF = "5ff462f"


def snapshot_backend(tmp_path: Path, ref: str) -> Path:
    """只从本地 Git 对象提取历史源码，不切分支或修改真实工作树。"""
    archive = subprocess.run(
        ["git", "archive", "--format=tar", ref, "backend"],
        cwd=ROOT,
        capture_output=True,
    )
    if archive.returncode:
        pytest.skip(f"需要本地 Git 历史中的 {ref}；源码 ZIP 不具备历史版本")
    old_root = tmp_path / "previous-release"
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tree:
        for member in tree.getmembers():
            if (
                member.isfile()
                and member.name.startswith("backend/")
                and ".." not in Path(member.name).parts
            ):
                out = old_root / member.name
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(tree.extractfile(member).read())
    return old_root


def test_old_release_upgrade_and_restore(tmp_path, isolated_env, record_property):
    """旧代码 v1 → 当前 v2 → 旧代码+迁移前副本；明确丢弃备份后的新写入。"""
    old_root = snapshot_backend(tmp_path, PREVIOUS_REF)

    headers = {"X-API-Key": isolated_env["API_TOKEN"]}
    database = Path(isolated_env["DB_PATH"])

    def old_service(env):
        port = free_port()
        return service(
            tmp_path,
            env,
            port=port,
            cwd=old_root,
            args=[
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                old_root / "backend",
                "--host",
                "127.0.0.1",
                "--port",
                port,
                "--workers",
                "1",
            ],
        )

    def schema(path):
        with sqlite3.connect(path) as db:
            return (
                [
                    row[0]
                    for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")
                ],
                [row[1] for row in db.execute("PRAGMA table_info(reminders)")],
            )

    with old_service(isolated_env) as (base, _):
        seed = httpx.post(
            base + "/api/tasks", headers=headers, json={"title": "迁移前记录"}, trust_env=False
        )
        assert seed.status_code == 201
        seed = seed.json()
    before = schema(database)
    assert before[0] == [1] and "wechat_user_id" not in before[1]
    backup = tmp_path / "pre-upgrade.db"
    backup_database(database, backup)

    with service(tmp_path, isolated_env) as (base, _):
        assert seed in httpx.get(base + "/api/tasks", headers=headers, trust_env=False).json()
        added = httpx.post(
            base + "/api/tasks", headers=headers, json={"title": "升级后新增"}, trust_env=False
        )
        assert added.status_code == 201
        added_id = added.json()["id"]
    after = schema(database)
    assert after[0] == [1, 2] and "wechat_user_id" in after[1]

    restored = tmp_path / "rollback-copy.db"
    backup_database(backup, restored)
    assert schema(restored) == before
    with old_service(dict(isolated_env, DB_PATH=str(restored))) as (base, _):
        assert httpx.get(base + "/api/tasks", headers=headers, trust_env=False).json() == [seed]
    assert schema(database) == after, "升级后原库须保留，不能被回滚覆盖"
    record_property("previous_code", PREVIOUS_REF)
    record_property("schema_before", before[0])
    record_property("schema_after", after[0])
    record_property("excluded_post_backup_task_id", added_id)


def test_tools_with_current_develop_backend(tmp_path, isolated_env, record_property):
    """部署工具同时兼容当前 develop 后端，避免为部署旧 C4 包而降级 C3。"""
    source = snapshot_backend(tmp_path, "origin/develop")
    revision = subprocess.check_output(
        ["git", "rev-parse", "origin/develop"],
        cwd=ROOT,
        text=True,
    ).strip()
    port = free_port()
    args = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--app-dir",
        source / "backend",
        "--host",
        "127.0.0.1",
        "--port",
        port,
        "--workers",
        "1",
    ]
    with service(tmp_path, isolated_env, port=port, args=args, cwd=source) as (base, _):
        result = run(
            [sys.executable, ROOT / "scripts/check_deployment.py", base, "--exercise"],
            isolated_env,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "14/14" in result.stdout
    record_property("compatible_develop", revision)


def test_server_rollback_cli(tmp_path, isolated_env):
    """用户交付脚本实际启动两代代码、迁移、恢复，并保留备份和升级副本。"""
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
    result = run(
        [
            sys.executable,
            ROOT / "scripts/check_server_rollback.py",
            "--repo",
            ROOT,
            "--current-ref",
            "HEAD",
            "--output-parent",
            tmp_path,
        ],
        isolated_env,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["passed"] and report["old_code_reads_restored_data"]
    assert report["production_database_opened"] is False
    assert report["production_service_changed"] is False
    directory = Path(report["directory"])
    assert directory.is_relative_to(tmp_path)
    with sqlite3.connect(directory / "restored.db") as restored:
        assert restored.execute("SELECT title FROM tasks").fetchall() == [("c4-before-upgrade",)]
    with sqlite3.connect(directory / "exercise.db") as upgraded:
        assert upgraded.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2
    assert (directory / "before-upgrade.db").is_file()
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT) == head
    assert isolated_env["API_TOKEN"] not in result.stdout + result.stderr


def test_server_rollback_rejects_mismatched_source(tmp_path, isolated_env):
    """指定版本与工作树不符时在建库/启进程前拒绝，不自动切分支。"""
    result = run(
        [
            sys.executable,
            ROOT / "scripts/check_server_rollback.py",
            "--repo",
            ROOT,
            "--current-ref",
            PREVIOUS_REF,
            "--output-parent",
            tmp_path,
        ],
        isolated_env,
    )
    assert result.returncode != 0
    assert json.loads(result.stdout)["passed"] is False
    assert list(tmp_path.iterdir()) == []
