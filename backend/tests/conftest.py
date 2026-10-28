"""后端测试配置：数据库指向临时目录，注入测试 token。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def disable_real_wechat(monkeypatch):
    """普通测试禁止真实微信渠道；B3 专项测试显式启用 MockTransport。"""
    monkeypatch.setattr(config, "WX_ENABLED", False)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "API_TOKEN", "test-token")
    monkeypatch.setattr(config, "SCHEDULER_ENABLED", False)
    db.init_db()
    with TestClient(app) as c:
        yield c
