"""B7 草稿不落库、确认才安排提醒，且超时与坏输出有稳定的接口结果。"""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from app import config, db, vision

H = {"X-API-Key": "test-token"}
BASE = {"reference_at": "2026-10-30T12:00:00+08:00", "timezone": "Asia/Shanghai"}


def parse(client, text):
    response = client.post("/api/tasks/parse-text", headers=H, json={**BASE, "text": text})
    assert response.status_code == 200, response.text
    return response.json()["drafts"]


def test_multiple_drafts_confirm_only_one(client):
    first, second = parse(client, "明天下午三点提醒我交实验报告，备注：附源代码；下周五前交报告")
    assert first["remind_at"] == "2026-10-31T15:00:00+08:00"
    assert first["note"] == "附源代码"
    assert first["due_at"] is None and not first["needs_confirmation"]
    assert second["due_at"] == "2026-11-06" and second["remind_at"] is None
    assert db.list_tasks() == db.list_reminders() == []
    saved = client.post(
        "/api/tasks",
        headers=H,
        json={k: first[k] for k in ("title", "note", "due_at", "remind_at")},
    )
    assert saved.status_code == 201
    reminders = db.list_reminders()
    assert (
        len(reminders) == 1
        and reminders[0]["task_id"] == saved.json()["id"]
        and reminders[0]["channel"] == "pc"
    )


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("买笔", "date"),
        ("周五晚上提醒我买笔", "date"),
        ("明天晚上提醒我交作业", "remind_at"),
        ("昨天上午九点提醒我开会", "past"),
        ("2026-02-30提醒我提交", "date"),
    ],
)
def test_uncertain_and_past(client, text, field):
    item = parse(client, text)[0]
    assert field in item["needs_confirmation"]
    if field != "past":
        assert item["remind_at"] is None


def test_malformed_model_parts(client, monkeypatch):
    monkeypatch.setattr(config, "LLM_TEXT_MODEL", "test-model")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://example.invalid")
    monkeypatch.setattr(config, "LLM_API_KEY", "fixture")
    monkeypatch.setattr(vision, "chat_content", AsyncMock(return_value='{"parts":["fabricated"]}'))
    r = client.post("/api/tasks/parse-text", headers=H, json={**BASE, "text": "交报告然后去上课"})
    assert r.status_code == 502 and not db.list_tasks()


def test_text_requires_reference_zone_and_auth(client):
    for patch in (
        {"reference_at": "2026-10-30"},
        {"timezone": "not/a/zone"},
        {"text": " "},
        {"text": "a" * 2001},
    ):
        assert (
            client.post(
                "/api/tasks/parse-text", headers=H, json={**BASE, "text": "明天开会", **patch}
            ).status_code
            == 422
        )
    assert (
        client.post("/api/tasks/parse-text", json={**BASE, "text": "明天开会"}).status_code == 401
    )


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (httpx.ConnectError("offline"), vision.VisionError),
        (429, vision.VisionRateLimited),
        (200, vision.VisionError),
        (httpx.ReadTimeout("slow"), vision.VisionTimeout),
    ],
)
def test_provider_failures(monkeypatch, failure, expected):
    client_type = httpx.AsyncClient

    def handle(request):
        if isinstance(failure, Exception):
            raise failure
        return httpx.Response(failure, json={"choices": []})

    monkeypatch.setattr(config, "LLM_BASE_URL", "https://example.invalid")
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handle), **kw)
    )
    with pytest.raises(expected):
        asyncio.run(vision.chat_content("test", []))


def test_real_image_fixture_and_deadline(client, monkeypatch):
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[2] / "tests_fixtures/b7/schedule.png"
    files = {"image": ("schedule.png", fixture.read_bytes(), "image/png")}

    async def slow(*args):
        await asyncio.sleep(2)

    monkeypatch.setattr(config, "PARSE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(vision, "parse_schedule_image", slow)
    response = client.post("/api/courses/parse-image", headers=H, files=files)
    assert response.status_code == 504
    assert response.json()["detail"]["code"] == "parse_timeout"
    assert not db.list_courses()
