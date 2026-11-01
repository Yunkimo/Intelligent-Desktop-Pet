"""B8 停服后显式升级指定数据库；先备份、事务迁移、幂等重跑。"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import config, db  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--service-stopped", action="store_true", required=True)
    args = parser.parse_args()
    path = args.db.resolve()
    if not path.is_file():
        parser.error("数据库必须是已有文件；不自动创建或覆盖指定路径")
    config.DB_PATH = path
    before = set(path.parent.glob(path.stem + ".pre-b8-*.db"))
    db.init_db()
    with db._conn() as conn:
        result = {
            "schema_version": 3,
            "default_user_id": 1,
            "counts": {
                t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("courses", "tasks", "reminders")
            },
            "foreign_key_ok": not conn.execute("PRAGMA foreign_key_check").fetchall(),
            "backups": [str(p) for p in set(path.parent.glob(path.stem + ".pre-b8-*.db")) - before],
        }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
