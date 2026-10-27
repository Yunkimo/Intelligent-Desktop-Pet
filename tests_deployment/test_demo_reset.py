"""验证重置的默认拒绝、备份恢复及失败保护。"""

import sqlite3
from contextlib import closing

import pytest
from backup_backend_db import backup_database
from reset_demo import create_demo, demo_path, reset_database, verify_demo


def test_reset_backup_and_repeat(tmp_path):
    """明确标记的演示库重置后保留备份；恢复副本可读到原数据。"""
    root = tmp_path / "data"
    path = demo_path(root / "demo-review.db", root)
    create_demo(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE payload (value TEXT)")
        db.execute("INSERT INTO payload VALUES ('before-reset')")
        db.commit()
    backup = reset_database(path, tmp_path / "backups")
    verify_demo(path)
    restored = tmp_path / "restored.db"
    backup_database(backup, restored)
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute("SELECT value FROM payload").fetchone() == ("before-reset",)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='payload'").fetchone() is None
    assert reset_database(path, tmp_path / "backups") != backup


@pytest.mark.parametrize("name", ["pet.db", "ordinary.db", "../demo-escape.db"])
def test_forbidden_paths(tmp_path, name):
    """普通默认库及越界路径不能被重置。"""
    with pytest.raises(ValueError):
        demo_path(tmp_path / "data" / name, tmp_path / "data")


def test_unmarked_and_existing_init(tmp_path):
    """名字像演示库仍不足以授权删除；init 不能给已有库补标记。"""
    path = tmp_path / "demo-existing.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE real_data (value TEXT)")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        reset_database(path, tmp_path / "backups")
    with pytest.raises(FileExistsError):
        create_demo(path)
    assert path.read_bytes() == before


def test_sidecar_and_backup_failure_keep_original(tmp_path):
    """疑似在线 WAL 与备份不可写时保留原库。"""
    path = tmp_path / "demo-test.db"
    create_demo(path)
    before = path.read_bytes()
    wal = path.with_name(path.name + "-wal")
    wal.touch()
    with pytest.raises(ValueError):
        reset_database(path, tmp_path / "backups")
    wal.unlink()
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupied")
    with pytest.raises(OSError):
        reset_database(path, blocked)
    assert path.read_bytes() == before
