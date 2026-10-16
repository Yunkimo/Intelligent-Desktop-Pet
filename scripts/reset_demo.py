"""演示数据库重置：仅作用于明确标记的演示库，绝不触碰真实用户数据。

- 只接受 backend/.env 中 DB_PATH 指向的库，且路径必须位于 backend/data/ 之下
- 重置前用 backup_backend_db.backup_database 做一致性备份
- 需 --yes 显式确认；输出备份路径供回滚

在 backend 虚拟环境运行：
    backend/.venv/Scripts/python scripts/reset_demo.py --yes
"""

import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import os  # noqa: E402

from backup_backend_db import backup_database  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")

DB_PATH = Path(os.getenv("DB_PATH", str(ROOT / "backend" / "data" / "pet.db")))
ALLOWED_ROOT = (ROOT / "backend" / "data").resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="确认执行重置")
    args = parser.parse_args()

    if DB_PATH.resolve().parent != ALLOWED_ROOT:
        print(f"拒绝：DB_PATH={DB_PATH} 不在演示库目录 {ALLOWED_ROOT} 下，疑似真实用户数据")
        sys.exit(1)
    if not args.yes:
        print(f"预览：将备份并删除演示库 {DB_PATH}。确认执行请加 --yes")
        sys.exit(0)

    if not DB_PATH.is_file():
        print(f"演示库 {DB_PATH} 不存在，无需重置")
        return

    backup = DB_PATH.with_name(f"{DB_PATH.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    backup_database(DB_PATH, backup)
    print(f"已备份：{backup}")

    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(DB_PATH) + suffix)
        if candidate.is_file():
            candidate.unlink()
            print(f"已删除：{candidate}")
    print("重置完成；重启后端将自动建空库。回滚：停止后端后把备份复制回 pet.db")


if __name__ == "__main__":
    main()
