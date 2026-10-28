"""应用路径解析。"""

from pathlib import Path


def app_dir() -> Path:
    """应用根目录：本项目根目录（pet/ 的上一级）。"""
    return Path(__file__).resolve().parent.parent
