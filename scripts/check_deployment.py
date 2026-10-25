"""部署自检：默认只读；--exercise 验证临时业务写入、事件、重连和清理。"""

import argparse
import base64
import json
import os
import secrets
import ssl
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]


def endpoints(base: str) -> tuple[str, str]:
    """校验入口地址，保留路径前缀并按 HTTPS 派生 WSS。"""
    parts = urlsplit(base)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError("入口需为不带用户信息、查询参数或片段的 HTTP(S) URL")
    _ = parts.port
    path = parts.path.rstrip("/")
    http = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    ws = urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc, path, "", ""))
    return http, ws


def check_deployment(base: str, token: str, ca_file: str | None = None) -> list[tuple[str, bool]]:
    """执行七项只读检查；网络/TLS/代理错误不能冒充鉴权拒绝。"""
    base, ws_base = endpoints(base)
    context = ssl.create_default_context(cafile=ca_file)
    results = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok))
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f"：{detail}" if detail else ""))

    wrong = secrets.token_hex(24)
    while wrong == token:
        wrong = secrets.token_hex(24)
    with httpx.Client(verify=context, trust_env=False, timeout=5, follow_redirects=False) as client:
        cases = [
            ("健康检查", "/api/health", {}, 200),
            ("REST 无凭据拒绝", "/api/courses", {}, 401),
            ("REST 错误凭据拒绝", "/api/courses", {"X-API-Key": wrong}, 401),
            ("REST 正确凭据放行", "/api/courses", {"X-API-Key": token}, 200),
        ]
        for name, path, headers, expected in cases:
            try:
                response = client.get(base + path, headers=headers)
                ok = response.status_code == expected
                if name == "健康检查":
                    ok = ok and response.json() == {"status": "ok"}
                elif expected == 200:
                    ok = ok and isinstance(response.json(), list)
                record(name, ok, f"HTTP {response.status_code}")
            except (httpx.HTTPError, ValueError) as exc:
                # 不输出异常正文：其中可能包含带 token 的 URL 或代理信息。
                record(name, False, type(exc).__name__)
    for name, value, expected in [
        ("WS 正确凭据握手", token, 101),
        ("WS 无凭据拒绝", None, 403),
        ("WS 错误凭据拒绝", wrong, 403),
    ]:
        url = ws_base + "/ws" + ("?" + urlencode({"token": value}) if value is not None else "")
        options = {"ssl": context} if ws_base.startswith("wss:") else {}
        if expected == 403:
            # 使用完整 RFC 6455 Upgrade 请求验证拒绝，不建立本应被拒绝的 WS 会话。
            # httpx 正常消费拒绝响应，避免部分 Windows TLS 栈上负向 WS 会话关闭的竞态。
            try:
                with httpx.Client(verify=context, trust_env=False, timeout=5) as client:
                    response = client.get(
                        base
                        + "/ws"
                        + ("?" + urlencode({"token": value}) if value is not None else ""),
                        headers={
                            "Connection": "Upgrade",
                            "Upgrade": "websocket",
                            "Sec-WebSocket-Version": "13",
                            "Sec-WebSocket-Key": base64.b64encode(secrets.token_bytes(16)).decode(
                                "ascii"
                            ),
                        },
                    )
                    record(name, response.status_code == 403, f"HTTP {response.status_code}")
            except (httpx.HTTPError, ValueError) as exc:
                record(name, False, type(exc).__name__)
            continue
        try:
            with connect(url, open_timeout=5, close_timeout=2, proxy=None, **options) as ws:
                record(name, expected == 101 and ws.response.status_code == 101, "HTTP 101")
        except InvalidStatus as exc:
            code = exc.response.status_code
            record(name, expected == 403 and code == 403, f"HTTP {code}")
        except Exception as exc:
            record(name, False, type(exc).__name__)
    return results


def exercise_deployment(
    base: str, token: str, ca_file: str | None = None
) -> list[tuple[str, bool]]:
    """显式选择后才写入无提醒的临时日程/课程，只清理本轮确认拥有的记录。"""
    base, ws_base = endpoints(base)
    context = ssl.create_default_context(cafile=ca_file)
    label = "c4-check-" + secrets.token_hex(8)
    print(f"临时业务标识：{label}；若响应丢失请人工按此标识核查，不自动重试创建")
    results: list[tuple[str, bool]] = []
    created: list[tuple[str, str, int]] = []
    url = ws_base + "/ws?" + urlencode({"token": token})
    options = {"ssl": context} if ws_base.startswith("wss:") else {}

    def record(name: str, ok: bool) -> None:
        results.append((name, ok))
        print(f"{'PASS' if ok else 'FAIL'} {name}")

    def rows(client: httpx.Client, table: str) -> list[dict]:
        response = client.get(f"api/{table}")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise ValueError("业务响应不是记录列表")
        return data

    def event_received(ws, event_type: str, row_id: int) -> bool:
        deadline = time.monotonic() + 5
        while (remaining := deadline - time.monotonic()) > 0:
            event = json.loads(ws.recv(timeout=remaining))
            if (
                isinstance(event, dict)
                and event.get("version") == 1
                and event.get("type") == event_type
                and isinstance(event.get("data"), dict)
                and event["data"].get("id") == row_id
                and event.get("event_id")
            ):
                return True
        return False

    with httpx.Client(
        base_url=base + "/",
        headers={"X-API-Key": token},
        verify=context,
        trust_env=False,
        timeout=5,
        follow_redirects=False,
    ) as client:
        stage = "业务 WS 建连"
        try:
            with connect(url, open_timeout=5, close_timeout=2, proxy=None, **options) as ws:
                for table, field, payload, event_type in [
                    ("tasks", "title", {"title": label}, "task.created"),
                    (
                        "courses",
                        "name",
                        {
                            "name": label,
                            "day_of_week": 1,
                            "start_time": "08:00",
                            "end_time": "09:00",
                        },
                        "course.created",
                    ),
                ]:
                    stage = f"{table} 创建"
                    response = client.post(f"api/{table}", json=payload)
                    response.raise_for_status()
                    data = response.json()
                    if (
                        response.status_code != 201
                        or not isinstance(data, dict)
                        or type(data.get("id")) is not int
                        or data["id"] <= 0
                        or data.get(field) != label
                    ):
                        raise ValueError("创建结果无法确认；按标识人工核查")
                    created.append((table, field, data["id"]))
                    stage = f"{table} REST 读回"
                    record(
                        f"{table} 写入并读回",
                        any(
                            row.get("id") == data["id"] and row.get(field) == label
                            for row in rows(client, table)
                        ),
                    )
                    stage = f"{table} WS 业务事件"
                    record(
                        f"{table} WebSocket 业务事件", event_received(ws, event_type, data["id"])
                    )
            stage = "WS 重连与 REST 校正"
            with connect(url, open_timeout=5, close_timeout=2, proxy=None, **options):
                record(
                    "主动断开后重连并 REST 校正",
                    all(
                        any(
                            row.get("id") == row_id and row.get(field) == label
                            for row in rows(client, table)
                        )
                        for table, field, row_id in created
                    ),
                )
        except Exception as exc:
            # 不打印异常正文/URL，也不因超时重发创建。
            record(f"{stage}失败（{type(exc).__name__}）", False)
        finally:
            for table, field, row_id in reversed(created):
                try:
                    current = [row for row in rows(client, table) if row.get("id") == row_id]
                    if current and current[0].get(field) != label:
                        raise ValueError("记录已被他人修改，保留现场")
                    if current:
                        response = client.delete(f"api/{table}/{row_id}")
                        if response.status_code != 204:
                            raise ValueError("清理未确认")
                    record(
                        f"{table} 临时数据清理并读回",
                        all(row.get("id") != row_id for row in rows(client, table)),
                    )
                except Exception as exc:
                    record(f"{table} 清理失败（{type(exc).__name__}；按临时标识人工核查）", False)
    return results


def main() -> int:
    """读取本地配置；任一失败返回非零，不关闭 TLS 验证。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", nargs="?", default="http://127.0.0.1:8001")
    parser.add_argument("--env-file", type=Path, default=ROOT / "backend/.env")
    parser.add_argument("--ca-file", help="自建 CA 的 PEM 文件；默认使用系统可信 CA")
    parser.add_argument(
        "--exercise", action="store_true", help="显式创建并清理两条无提醒临时业务记录"
    )
    args = parser.parse_args()
    load_dotenv(args.env_file)
    token = os.getenv("API_TOKEN", "").strip()
    if not token or token == "change-me-to-a-random-string":
        print("FAIL 请在环境变量或配置文件中设置实际 API_TOKEN")
        return 1
    try:
        results = check_deployment(args.base_url, token, args.ca_file)
        if args.exercise and all(ok for _, ok in results):
            results += exercise_deployment(args.base_url, token, args.ca_file)
    except (ValueError, OSError) as exc:
        print(f"FAIL 自检配置无效：{type(exc).__name__}")
        return 1
    passed = sum(ok for _, ok in results)
    print(f"结果：{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
