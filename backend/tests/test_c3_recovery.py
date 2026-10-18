"""C3 服务端协作：真实事务、会话和调度；微信平台沿用独立模拟。"""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from app import db, reminder_store, wechat_store
from test_wechat import HEADERS, dispatch, login
from test_wechat import wx_app as wx_app  # noqa: F401
from test_wechat import wx_config as wx_config  # noqa: F401


def prepare(client):
    """建立日程和用户，取得可重复调用的创建入口。"""
    identity, headers = login(client)
    task = client.post(
        "/api/tasks",
        headers=HEADERS,
        json={"title": "C3 回归", "remind_at": "2040-01-01T08:00:00+08:00"},
    ).json()
    response = client.post("/api/wechat/reminders", headers=headers, json={"task_id": task["id"]})
    assert response.status_code == 200, response.text
    reminder = response.json()
    payload = {
        "reminder_id": reminder["id"],
        "event_id": reminder["event_id"],
        "template_id": "test-template",
        "request_id": str(uuid4()),
        "result": "accept",
    }
    return task, reminder, identity, headers, payload


def test_concurrent_creation_and_replay(wx_app):
    client, _ = wx_app
    task, reminder, identity, headers, _ = prepare(client)
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(
            pool.map(lambda _: db.ensure_phone_reminder(task["id"], identity["user_id"]), range(16))
        )
    assert {r["id"] for r in rows} == {reminder["id"]}
    assert {r["event_id"] for r in rows} == {reminder["event_id"]}
    assert len(db.list_reminders()) == 1
    # 即使响应被丢弃，再请求仍返回同一资源。
    again = client.post("/api/wechat/reminders", headers=headers, json={"task_id": task["id"]})
    assert again.json()["id"] == reminder["id"]


def test_same_instant_keeps_event_and_single_send(wx_app):
    client, fake = wx_app
    task, reminder, _, headers, payload = prepare(client)
    assert client.post("/api/wechat/subscribe", headers=headers, json=payload).status_code == 200
    assert dispatch(client) == 1
    for value in ["2040-01-01T08:00", "2040-01-01T00:00:00.000000Z"]:
        assert (
            client.put(
                "/api/tasks/" + str(task["id"]), headers=HEADERS, json={"remind_at": value}
            ).status_code
            == 200
        )
        updated = db.ensure_phone_reminder(task["id"], 1)
        assert updated["event_id"] == reminder["event_id"]
        assert updated["done"] == 1
    assert (
        client.post("/api/wechat/subscribe", headers=headers, json=payload).json()["status"]
        == "sent"
    )
    assert dispatch(client) == 0
    assert fake.count("/cgi-bin/message/subscribe/send") == 1


@pytest.mark.parametrize("operation", ["reschedule", "clear", "delete"])
def test_task_mutation_cancels_old_send_atomically(wx_app, operation):
    client, fake = wx_app
    task, reminder, _, headers, payload = prepare(client)
    client.post("/api/wechat/subscribe", headers=headers, json=payload)
    if operation == "delete":
        response = client.delete("/api/tasks/" + str(task["id"]), headers=HEADERS)
    else:
        response = client.put(
            "/api/tasks/" + str(task["id"]),
            headers=HEADERS,
            json={"remind_at": "2041-01-01T08:00+08:00" if operation == "reschedule" else None},
        )
    assert response.is_success
    if operation == "reschedule":
        assert wechat_store.status(reminder["id"])[0]["status"] == "cancelled"
        assert reminder_store.delivery_status(reminder["id"])["event_id"] != reminder["event_id"]
        stale = client.post("/api/wechat/subscribe", headers=headers, json=payload)
        assert stale.status_code == 409
        assert stale.json()["detail"] == "reminder_event_changed"
    else:
        assert db.list_reminders() == []
    assert dispatch(client) == 0
    assert fake.count("/cgi-bin/message/subscribe/send") == 0


def test_landing_target_identity_and_latest_task(wx_app):
    client, fake = wx_app
    task, reminder, _, headers, payload = prepare(client)
    client.post("/api/wechat/subscribe", headers=headers, json=payload)
    dispatch(client)
    import json

    sent = next(r for r in fake.calls if r.url.path.endswith("/subscribe/send"))
    assert (
        json.loads(sent.content)["page"] == f"pages/reminder/reminder?reminder_id={reminder['id']}"
    )
    route = "/api/wechat/reminders/" + str(reminder["id"])
    client.put("/api/tasks/" + str(task["id"]), headers=HEADERS, json={"title": "最新标题"})
    assert client.get(route, headers=headers).json()["task"]["title"] == "最新标题"
    _, other = login(client, "bob")
    assert client.get(route, headers=other).status_code == 404
    assert client.get(route, headers=HEADERS).status_code == 401
    assert (
        client.post(
            "/api/wechat/reminders", headers=other, json={"task_id": task["id"], "user_id": 1}
        ).status_code
        == 422
    )
    client.delete("/api/tasks/" + str(task["id"]), headers=HEADERS)
    assert client.get(route, headers=headers).status_code == 404


def test_invalid_task_time_rejected_without_mutation(wx_app):
    client, _ = wx_app
    task, reminder, _, _, _ = prepare(client)
    response = client.put(
        "/api/tasks/" + str(task["id"]), headers=HEADERS, json={"remind_at": "invalid"}
    )
    assert response.status_code == 422
    assert reminder_store.delivery_status(reminder["id"])["event_id"] == reminder["event_id"]


def test_reschedule_transaction_rolls_back_on_failure(wx_app, monkeypatch):
    """更新提醒中途失败时日程和旧授权一并回滚，不出现半次保存。"""
    client, _ = wx_app
    task, reminder, _, headers, payload = prepare(client)
    client.post("/api/wechat/subscribe", headers=headers, json=payload)

    def fail_seed(*args):
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr(reminder_store, "seed_delivery", fail_seed)
    with pytest.raises(RuntimeError, match="injected"):
        db.update_task(task["id"], {"remind_at": "2041-01-01T08:00+08:00"})
    assert db.list_tasks()[0]["remind_at"] == task["remind_at"]
    assert reminder_store.delivery_status(reminder["id"])["event_id"] == reminder["event_id"]
    assert wechat_store.status(reminder["id"])[0]["status"] == "pending"
