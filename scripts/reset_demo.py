"""重置明确标记的演示库；要求停服，先备份再替换，默认只预览。"""

import argparse
import re
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from backup_backend_db import backup_database

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "backend/data"
MARKER = "disposable-c4-v1"


def demo_path(path: Path, allowed_root: Path = DATA_ROOT) -> Path:
    """仅允许专用目录中的 demo-*.db，拒绝符号链接和普通默认库。"""
    if not path.is_absolute():
        path = ROOT / path
    if path.is_symlink() or allowed_root.is_symlink():
        raise ValueError("演示库不能使用符号链接")
    resolved = path.resolve()
    if resolved.parent != allowed_root.resolve() or not re.fullmatch(
        r"demo-[A-Za-z0-9_-]+\.db", resolved.name
    ):
        raise ValueError("必须明确指定 backend/data/demo-名称.db；禁止默认 pet.db 或越界路径")
    return resolved


def create_demo(path: Path) -> None:
    """只初始化不存在的演示库；不能给现有普通库追加可删除标记。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb"):
        pass
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE c4_demo_guard (purpose TEXT NOT NULL)")
        connection.execute("INSERT INTO c4_demo_guard VALUES (?)", (MARKER,))
        connection.commit()


def verify_demo(path: Path) -> None:
    """只读检查库内标记，不修改未标记数据库。"""
    if not path.is_file():
        raise ValueError("演示库不存在；首次使用请显式 --init")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as connection:
        try:
            rows = connection.execute("SELECT purpose FROM c4_demo_guard").fetchall()
        except sqlite3.Error as exc:
            raise ValueError("数据库没有演示标记，拒绝重置") from exc
        if rows != [(MARKER,)]:
            raise ValueError("演示标记不匹配，拒绝重置")


def reset_database(path: Path, backup_dir: Path) -> Path:
    """在操作者确认停服后备份并替换；WAL/SHM 或独占锁冲突时拒绝。"""
    verify_demo(path)
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("发现 SQLite sidecar，请先正常停止后端并检查数据库；不自动删除")
    with closing(sqlite3.connect(path, timeout=1)) as connection:
        connection.execute("BEGIN EXCLUSIVE")
        connection.rollback()
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{path.stem}-{time.time_ns()}.db"
    backup_database(path, backup)
    replacement = path.with_name(f".{path.name}-{uuid.uuid4().hex}.new")
    try:
        create_demo(replacement)
        replacement.replace(path)
    finally:
        replacement.unlink(missing_ok=True)
    return backup


def main() -> int:
    """处理显式初始化、预览及确认重置；失败保留原库和诊断备份。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path, help="仓库相对路径或绝对路径")
    parser.add_argument("--init", action="store_true", help="新建不存在的专用演示库")
    parser.add_argument("--yes", action="store_true", help="执行重置；默认仅预览")
    parser.add_argument("--stopped", action="store_true", help="确认已停止所有使用此库的服务")
    args = parser.parse_args()
    try:
        path = demo_path(args.database)
        if args.init:
            if args.yes or args.stopped:
                parser.error("--init 不能与重置参数混用")
            create_demo(path)
            print(f"已初始化演示库：{path}")
            return 0
        verify_demo(path)
        if not args.yes:
            print(f"预览：将备份并重置 {path}；停服后使用 --yes --stopped")
            return 0
        if not args.stopped:
            raise ValueError("重置前必须停止后端，并通过 --stopped 确认")
        backup = reset_database(path, path.parent.parent / "backups")
        print(f"重置完成：{path}\n完整备份：{backup}")
        print("恢复：停服后将备份复制到一个新路径校验，再将 DB_PATH 指向该恢复副本。")
        return 0
    except (ValueError, OSError, sqlite3.Error, TimeoutError) as exc:
        print(f"拒绝或失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
