from datetime import datetime, timedelta, timezone

from app import config, wechat_store


def account(name):
    session = wechat_store.new_session(name)
    return session["session_token"], {"Authorization": "Bearer " + session["session_token"]}


def test_capture_shares_with_paired_device_and_isolates_other_accounts(client, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_LEGACY_API_KEY", False)
    token, phone = account("capture-alice")
    _, other = account("capture-bob")
    code = client.post("/api/auth/pairing", headers=phone).json()["pairing_code"]
    device = client.post("/api/auth/device", json={"pairing_code": code}).json()["device_token"]
    desktop = {"Authorization": "Bearer " + device}
    text = "2040-01-07 18:00前交报告，17:00还没交就提醒我"
    payload = {"text": text, "request_id": "same-id"}
    assert (
        client.post("/api/capture", json=payload, headers={"X-API-Key": "test-token"}).status_code
        == 401
    )
    with client.websocket_connect("/ws?token=" + token) as ws:
        response = client.post("/api/capture", json=payload, headers=desktop)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["kind"] == "todo"
        task = result["item"]
        assert task["due_at"] == "2040-01-07T18:00:00+08:00"
        assert ws.receive_json()["data"] == {"id": task["id"]}
    assert client.post("/api/capture", json=payload, headers=phone).json() == result
    assert client.get("/api/tasks", headers=phone).json() == [task]
    assert client.get("/api/tasks", headers=other).json() == []
    assert client.get("/api/reminders", headers=other).json() == []
    reminder = client.get("/api/reminders", headers=phone).json()[0]
    assert reminder["task_id"] == task["id"]
    assert client.get(f"/api/reminders/{reminder['id']}", headers=other).status_code == 404
    assert (
        client.put(f"/api/tasks/{task['id']}", json={"done": True}, headers=phone).status_code
        == 200
    )
    delivery = client.get(f"/api/reminders/{reminder['id']}/delivery", headers=desktop).json()
    assert delivery["status"] == "cancelled"


def test_capture_clarification_is_private_and_confirm_is_idempotent(client):
    _, owner = account("choices-alice")
    _, other = account("choices-bob")
    response = client.post(
        "/api/capture", headers=owner, json={"request_id": "choice", "text": "明天三点交报告"}
    ).json()
    assert response["status"] == "needs_clarification"
    assert {choice["kind"] for choice in response["choices"]} == {"todo", "schedule", "reminder"}
    assert client.get("/api/tasks", headers=owner).json() == []
    selected = next(i for i, row in enumerate(response["choices"], 1) if row["kind"] == "reminder")
    path = "/api/capture/choice/confirm"
    assert client.post(path, headers=other, json={"option": selected}).status_code == 404
    created = client.post(path, headers=owner, json={"option": selected}).json()
    assert created["kind"] == "reminder"
    assert client.post(path, headers=owner, json={"option": selected}).json() == created
    assert len(client.get("/api/reminders", headers=owner).json()) == 1


def test_schedule_relative_reminder_moves_with_start(client):
    _, owner = account("schedule-alice")
    response = client.post(
        "/api/capture",
        headers=owner,
        json={"request_id": "meeting", "text": "明早九点开会，提前十分钟提醒我"},
    ).json()
    assert response["kind"] == "schedule"
    task = response["item"]
    assert task["due_at"] is None and "T09:00:" in task["start_at"]
    start = datetime.fromisoformat(task["start_at"]) + timedelta(hours=1)
    updated = client.put(
        f"/api/tasks/{task['id']}", json={"start_at": start.isoformat()}, headers=owner
    )
    assert updated.status_code == 200, updated.text
    (reminder,) = client.get("/api/reminders", headers=owner).json()
    assert datetime.fromisoformat(reminder["remind_at"]) == (
        start - timedelta(minutes=10)
    ).astimezone(timezone.utc)


def test_capture_asks_before_creating_default_reminder(client):
    _, owner = account("default-reminder")
    payload = {"request_id": "default", "text": "明早九点开会"}
    prompt = client.post("/api/capture", headers=owner, json=payload).json()
    assert prompt["status"] == "needs_clarification"
    assert prompt["stage"] == "reminder"
    assert prompt["choices"][0]["choice_label"] == "提前 1 小时（默认）"
    assert client.get("/api/tasks", headers=owner).json() == []
    assert client.get("/api/reminders", headers=owner).json() == []
    selection = {"stage": "reminder", "option": 1}
    path = "/api/capture/default/confirm"
    confirmed = client.post(path, headers=owner, json=selection).json()
    assert confirmed["status"] == "created"
    task = confirmed["item"]
    assert task["remind_before_minutes"] == 60
    assert datetime.fromisoformat(task["start_at"]) - datetime.fromisoformat(
        task["remind_at"]
    ) == timedelta(hours=1)
    assert client.post(path, headers=owner, json=selection).json() == confirmed
    assert len(client.get("/api/reminders", headers=owner).json()) == 1


def test_ambiguous_capture_asks_for_reminder_after_item_confirmation(client):
    _, owner = account("skip-reminder")
    payload = {"request_id": "skip", "text": "明天下午三点交报告"}
    prompt = client.post("/api/capture", headers=owner, json=payload).json()
    item_choice = next(i for i, item in enumerate(prompt["choices"], 1) if item["kind"] == "todo")
    path = "/api/capture/skip/confirm"
    reminder_prompt = client.post(path, headers=owner, json={"option": item_choice}).json()
    assert reminder_prompt["stage"] == "reminder"
    assert client.post(path, headers=owner, json={"option": item_choice}).json() == reminder_prompt
    assert client.get("/api/tasks", headers=owner).json() == []
    choice = len(reminder_prompt["choices"])
    confirmed = client.post(
        path, headers=owner, json={"stage": "reminder", "option": choice}
    ).json()
    assert confirmed["item"]["kind"] == "todo"
    assert confirmed["item"]["remind_at"] is None
    assert client.get("/api/reminders", headers=owner).json() == []


def test_explicit_todo_reminder_moves_when_deadline_changes(client):
    _, owner = account("timed-deadline")
    payload = {"request_id": "deadline", "text": "明天18:00前交报告，提前一个小时提醒我"}
    result = client.post("/api/capture", headers=owner, json=payload).json()
    assert result["status"] == "created"
    task = result["item"]
    deadline = datetime.fromisoformat(task["due_at"]) + timedelta(hours=2)
    updated = client.put(
        f"/api/tasks/{task['id']}", headers=owner, json={"due_at": deadline.isoformat()}
    )
    assert updated.status_code == 200, updated.text
    (reminder,) = client.get("/api/reminders", headers=owner).json()
    assert datetime.fromisoformat(reminder["remind_at"]) == deadline - timedelta(hours=1)
