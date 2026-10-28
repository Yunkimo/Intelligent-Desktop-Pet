"""B3 可重复演示：真实应用/SQLite/调度器 + Mock 微信 HTTP，绝不发真实消息。"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import config, main, wechat_store  # noqa: E402
from app.reminder_time import utc_text  # noqa: E402
from app.wechat_client import WeChatClient  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def run(samples: int = 30) -> dict:
    """输出可量化缓存/幂等性证据，不输出 code、会话或微信凭证。"""
    calls = {"login": 0, "token": 0, "send": 0}

    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.weixin.qq.com"
        if request.url.path == "/sns/jscode2session":
            calls["login"] += 1
            return httpx.Response(200, json={"openid": "mock-user"})
        if request.url.path == "/cgi-bin/token":
            calls["token"] += 1
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 7200})
        if request.url.path == "/cgi-bin/message/subscribe/send":
            payload = json.loads(request.content)
            assert payload["touser"] == "mock-user"
            assert payload["template_id"] == "mock-template"
            calls["send"] += 1
            return httpx.Response(200, json={"errcode": 0})
        raise AssertionError("Unexpected WeChat endpoint")

    with tempfile.TemporaryDirectory(prefix="b3-smoke-") as directory:
        with (
            patch.multiple(
                config,
                DB_PATH=Path(directory) / "smoke.db",
                API_TOKEN="mock-api-key",
                WX_ENABLED=True,
                WX_APPID="mock-app",
                WX_SECRET="mock-secret",  # pragma: allowlist secret -- Mock-only placeholder
                WX_TEMPLATE_ID="mock-template",
                WX_TEMPLATE_FIELDS={"thing1": "title", "time2": "remind_at"},
                SCHEDULER_ENABLED=False,
                SCHEDULER_BATCH_SIZE=samples,
            ),
            patch.object(main, "WeChatClient", lambda: WeChatClient(httpx.MockTransport(upstream))),
        ):
            with TestClient(main.app) as client:
                headers = {"X-API-Key": "mock-api-key"}
                response = client.post(
                    "/api/wechat/login", headers=headers, json={"code": "mock-code"}
                )
                assert response.status_code == 200
                identity = response.json()
                authorized = {**headers, "Authorization": "Bearer " + identity["session_token"]}
                ids = []
                for index in range(samples):
                    created = client.post(
                        "/api/reminders",
                        headers=headers,
                        json={
                            "title": f"Mock 提醒 {index + 1}",
                            "remind_at": utc_text(time.time() - 1),
                            "channel": "phone",
                            "wechat_user_id": identity["user_id"],
                        },
                    )
                    assert created.status_code == 201
                    reminder_id = created.json()["id"]
                    payload = {
                        "reminder_id": reminder_id,
                        "request_id": str(uuid4()),
                        "template_id": "mock-template",
                        "result": "accept",
                    }
                    for _ in range(2):
                        assert (
                            client.post(
                                "/api/wechat/subscribe", headers=authorized, json=payload
                            ).status_code
                            == 200
                        )
                    ids.append(reminder_id)
                assert client.portal.call(main.app.state.scheduler.run_once) == samples
                assert client.portal.call(main.app.state.scheduler.run_once) == 0
                assert all(wechat_store.status(key)[0]["status"] == "sent" for key in ids)
                assert all(
                    row["done"] == 1 for row in client.get("/api/reminders", headers=headers).json()
                )
    assert calls == {"login": 1, "token": 1, "send": samples}
    return {
        "mode": "MockTransport; no real WeChat requests",
        "samples": samples,
        "accepted": samples,
        "replayed_subscriptions": samples,
        "duplicate_sends": 0,
        "calls": calls,
        "database": "temporary",
        "external_messages_sent": 0,
    }


def main_cli() -> None:
    """打印摘要，可选保存 JSON 实验记录。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.samples <= 1000:
        parser.error("samples 必须在 1 至 1000 之间")
    result = run(args.samples)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main_cli()
