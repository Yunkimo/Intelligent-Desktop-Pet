"""课表识别导入接口测试：parse-image 错误映射与 bulk 批量落库。"""

import sqlite3
from unittest.mock import AsyncMock

import pytest
from app import config, db, vision
from app.main import app

HEADERS = {"X-API-Key": "test-token"}

VALID_COURSE = {
    "name": "数学",
    "day_of_week": 1,
    "start_time": "08:00",
    "end_time": "09:40",
    "location": "A101",
    "teacher": "王老师",
    "weeks": [1, 2, 3],
}


def upload(client, monkeypatch=None):
    from pathlib import Path

    data = (Path(__file__).resolve().parents[2] / "tests_fixtures/b7/schedule.png").read_bytes()
    return client.post(
        "/api/courses/parse-image",
        headers=HEADERS,
        files={"image": ("timetable.jpg", data, "image/jpeg")},
    )


def test_parse_image_requires_token(client):
    response = client.post(
        "/api/courses/parse-image",
        files={"image": ("timetable.jpg", b"fake-image", "image/jpeg")},
    )
    assert response.status_code == 401


def test_parse_image_unconfigured_503(client, monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "LLM_BASE_URL", "")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "")
    response = upload(client)
    assert response.status_code == 503
    assert "LLM_API_KEY" in response.json()["detail"]


def test_parse_image_ok(client, monkeypatch):
    monkeypatch.setattr(
        vision,
        "parse_schedule_image",
        AsyncMock(return_value={"courses": [VALID_COURSE], "skipped": 0}),
    )
    response = upload(client)
    assert response.status_code == 200
    assert response.json() == {"courses": [VALID_COURSE], "skipped": 0}


def test_parse_image_no_courses_422(client, monkeypatch):
    monkeypatch.setattr(
        vision,
        "parse_schedule_image",
        AsyncMock(return_value={"courses": [], "skipped": 3}),
    )
    response = upload(client)
    assert response.status_code == 422


def test_parse_image_upstream_error_502(client, monkeypatch):
    monkeypatch.setattr(
        vision,
        "parse_schedule_image",
        AsyncMock(side_effect=vision.VisionError("上游返回 HTTP 401")),
    )
    response = upload(client)
    assert response.status_code == 502
    assert "Bearer" not in response.json()["detail"]


def test_parse_image_timeout_504(client, monkeypatch):
    monkeypatch.setattr(
        vision,
        "parse_schedule_image",
        AsyncMock(side_effect=vision.VisionTimeout("视觉模型响应超时")),
    )
    response = upload(client)
    assert response.status_code == 504


def test_parse_image_too_large_413(client, monkeypatch):
    monkeypatch.setattr(vision, "MAX_IMAGE_BYTES", 5)
    response = upload(client)
    assert response.status_code == 413


def test_bulk_requires_token(client):
    response = client.post("/api/courses/bulk", json={"courses": [VALID_COURSE]})
    assert response.status_code == 401


def test_bulk_creates_valid_skips_invalid(client):
    payload = {
        "courses": [
            VALID_COURSE,
            {**VALID_COURSE, "day_of_week": 8},
            {"day_of_week": 1},
        ]
    }
    response = client.post("/api/courses/bulk", headers=HEADERS, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert len(body["created"]) == 1
    assert body["created"][0]["weeks"] == "[1, 2, 3]"
    assert body["created"][0]["teacher"] == "王老师"
    assert len(body["skipped"]) == 2
    assert body["skipped"][0]["index"] == 1
    assert "reason" in body["skipped"][0]
    listed = client.get("/api/courses", headers=HEADERS).json()
    assert len(listed) == 1


def test_bulk_empty_list_422(client):
    response = client.post("/api/courses/bulk", headers=HEADERS, json={"courses": []})
    assert response.status_code == 422


def test_bulk_all_invalid_422(client):
    response = client.post(
        "/api/courses/bulk",
        headers=HEADERS,
        json={"courses": [{"name": "缺星期"}, {"day_of_week": 3}]},
    )
    assert response.status_code == 422
    assert db.list_courses() == []


def test_bulk_over_100_422(client):
    response = client.post(
        "/api/courses/bulk",
        headers=HEADERS,
        json={"courses": [VALID_COURSE] * 101},
    )
    assert response.status_code == 422


def test_bulk_coalesces_list_refresh(client, monkeypatch):
    notify = AsyncMock()
    monkeypatch.setattr(app.state.push_service, "notify", notify)
    payload = {"courses": [VALID_COURSE, {**VALID_COURSE, "name": "英语"}]}
    response = client.post("/api/courses/bulk", headers=HEADERS, json=payload)
    assert response.status_code == 201
    created_ids = [c["id"] for c in response.json()["created"]]
    assert notify.await_count == 1
    notified = [call.args for call in notify.await_args_list]
    assert notified == [("course.created", created_ids[0])]


def test_bulk_rollback_on_db_failure(client):
    rows = [
        VALID_COURSE,
        {**VALID_COURSE, "name": None},
    ]
    with pytest.raises(sqlite3.IntegrityError):
        db.create_courses_bulk(rows)
    assert db.list_courses() == []
