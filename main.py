"""入口：python main.py 启动桌面宠物；pythonw main.py 无控制台启动。"""

import sys
import traceback
from pathlib import Path

from pet.app import run

_ERROR_LOG = Path(__file__).resolve().parent / "data" / "pet-error.log"


def _log_startup_error() -> None:
    """把启动异常追加写入日志，供无控制台的 pythonw 启动方式排查。"""
    _ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _ERROR_LOG.open("a", encoding="utf-8") as fh:
        traceback.print_exc(file=fh)


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:
        _log_startup_error()
        raise
