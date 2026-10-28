"""使用 SQLite backup 复制数据库，拒绝覆盖已有目标。"""

import argparse
import sqlite3
import time
from contextlib import closing
from pathlib import Path


def backup_database(source: Path, destination: Path) -> None:
    """只读打开源库，创建新目标并校验；可用于停服后恢复到新路径。"""
    if not source.is_file():
        raise ValueError("源数据库不存在")
    # x 模式避免覆盖任何既有文件，也避免源目标相同。
    with destination.open("xb"):
        pass
    deadline = time.monotonic() + 30

    def check_progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() >= deadline:
            raise TimeoutError("SQLite backup exceeded 30 seconds")

    with closing(
        sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    ) as src:
        with closing(sqlite3.connect(destination, timeout=2)) as dst:
            src.backup(dst, pages=128, progress=check_progress, sleep=0.05)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("备份完整性检查失败，保留目标以供排查")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    backup_database(args.source, args.destination)
    print("SQLite backup and integrity check passed")
