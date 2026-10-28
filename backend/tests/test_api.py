"""后端 REST 接口测试：鉴权 + 三张表的 CRUD。"""


def test_health_public(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_requires_token(client):
    assert client.get("/api/tasks").status_code == 401


def test_wrong_token_rejected(client):
    resp = client.get("/api/tasks", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


def test_course_crud(client):
    headers = {"X-API-Key": "test-token"}
    payload = {
        "name": "高等数学",
        "day_of_week": 1,
        "start_time": "08:00",
        "end_time": "09:40",
        "location": "A101",
    }
    resp = client.post("/api/courses", json=payload, headers=headers)
    assert resp.status_code == 201
    course = resp.json()
    assert course["name"] == "高等数学"

    assert len(client.get("/api/courses", headers=headers).json()) == 1

    resp = client.put(f"/api/courses/{course['id']}", json={"name": "高数"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "高数"

    assert client.delete(f"/api/courses/{course['id']}", headers=headers).status_code == 204
    assert client.get("/api/courses", headers=headers).json() == []


def test_task_crud_and_partial_update(client):
    headers = {"X-API-Key": "test-token"}
    resp = client.post(
        "/api/tasks",
        json={"title": "复习英语", "note": "背单词", "remind_at": "2026-09-30T19:30:00"},
        headers=headers,
    )
    assert resp.status_code == 201
    task = resp.json()
    assert task["done"] == 0

    resp = client.put(f"/api/tasks/{task['id']}", json={"done": True}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["done"] == 1
    assert resp.json()["note"] == "背单词"  # 局部更新不覆盖其它字段


def test_reminder_crud(client):
    headers = {"X-API-Key": "test-token"}
    resp = client.post(
        "/api/reminders",
        json={"title": "喝水", "remind_at": "2026-09-30T15:00:00", "channel": "phone"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["channel"] == "phone"
    assert resp.json()["done"] == 0
