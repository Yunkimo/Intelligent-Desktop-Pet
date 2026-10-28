"""B4 真 HTTP + curl 验收；默认模拟上游，--live 才访问真实天气/搜索。"""

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def smoke_app():
    """仅冒烟进程使用此工厂，应用业务入口没有 Mock 开关。"""
    sys.path.insert(0, str(ROOT / "backend"))
    from app import main
    from app.web_query import WebQueryClient

    def upstream(request: httpx.Request) -> httpx.Response:
        if request.url.host == "wttr.in":
            response = httpx.Response(
                200,
                json={
                    "current_condition": [
                        {
                            "temp_C": "20",
                            "FeelsLikeC": "19",
                            "humidity": "50",
                            "weatherDesc": [{"value": "Sunny"}],
                            "localObsDateTime": "2040-01-01 12:00 PM",
                        }
                    ],
                    "nearest_area": [
                        {"areaName": [{"value": "Beijing"}], "country": [{"value": "China"}]}
                    ],
                },
            )
        else:
            assert request.url.host == "html.duckduckgo.com"
            response = httpx.Response(
                200,
                text='<a class="result__a" href="https://docs.python.org/3/">Python documentation</a><div class="result__snippet">Official Python documentation.</div>',
            )
        return httpx.Response(200, stream=httpx.ByteStream(response.content))

    if os.getenv("B4_SMOKE_LIVE") != "1":
        main.WebQueryClient = lambda: WebQueryClient(httpx.MockTransport(upstream))
    return main.app


def run(live: bool, proxy: str | None) -> dict:
    """临时库、随机 Key、随机本机端口；保存脱敏摘要与实际退出状态。"""
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("curl 未安装")
    records = []
    with tempfile.TemporaryDirectory(prefix="b4-curl-") as directory:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        token = secrets.token_urlsafe(32)
        curl_config = Path(directory) / "curl.conf"
        curl_config.write_text('header = "X-API-Key: ' + token + '"\n', encoding="utf-8")
        environment = {
            **os.environ,
            "API_TOKEN": token,
            "DB_PATH": str(Path(directory) / "smoke.db"),
            "SCHEDULER_ENABLED": "false",
            "WX_ENABLED": "false",
            "B4_SMOKE_LIVE": "1" if live else "0",
            "WEB_QUERY_TIMEOUT_SECONDS": "15",
        }
        if proxy:
            environment.update(HTTP_PROXY=proxy, HTTPS_PROXY=proxy)
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "scripts.smoke_backend_web_query:smoke_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--workers",
                    "1",
                ],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=log,
            )
            try:
                base_url = f"http://127.0.0.1:{port}"
                with httpx.Client(trust_env=False, timeout=2) as client:
                    deadline = time.monotonic() + 15
                    while True:
                        try:
                            client.get(base_url + "/api/health").raise_for_status()
                            break
                        except httpx.HTTPError:
                            if process.poll() is not None or time.monotonic() >= deadline:
                                raise RuntimeError("冒烟后端未就绪；请检查依赖和端口") from None
                            time.sleep(0.05)
                    assert client.get(base_url + "/api/tools/search?q=docs").status_code == 401
                for kind, parameter in [
                    ("weather", "city=Beijing"),
                    ("search", "q=Python asyncio official documentation"),
                ]:
                    started = time.monotonic()
                    response = subprocess.run(
                        [
                            curl,
                            "--silent",
                            "--show-error",
                            "--fail-with-body",
                            "--noproxy",
                            "*",
                            "--max-time",
                            "20",
                            "--config",
                            str(curl_config),
                            "--get",
                            base_url + "/api/tools/" + kind,
                            "--data-urlencode",
                            parameter,
                        ],
                        capture_output=True,
                        timeout=25,
                    )
                    try:
                        data = json.loads(response.stdout.decode("utf-8"))
                    except (UnicodeError, ValueError):
                        data = {"detail": "curl_non_json_response"}
                    records.append(
                        {
                            "kind": kind,
                            "curl_exit_code": response.returncode,
                            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                            "response": data,
                        }
                    )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    return {
        "mode": "live" if live else "mock upstream",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "transport": "real Uvicorn + curl, loopback, single worker",
        "database": "temporary",
        "unauthorized_status": 401,
        "proxy_used": bool(proxy),
        "results": records,
        "passed": len(records) == 2
        and all(
            row["curl_exit_code"] == 0 and row["response"].get("status") == "ok" for row in records
        ),
    }


def main_cli() -> None:
    """Mock 供 CI，live 用于人工复核公共服务实际可用性。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--proxy", help="仅传给验收子进程的受信任出口代理")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.live, args.proxy)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main_cli()
