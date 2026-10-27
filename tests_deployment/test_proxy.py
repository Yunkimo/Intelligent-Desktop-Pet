"""真实 Nginx 模板回归：Upgrade、TLS、上传边界和异常访问日志。"""

import os
import shutil
import ssl
import struct
import subprocess
import sys
import time
import zlib
from urllib.parse import quote

import httpx
import pytest
from conftest import CREATE_FLAGS, ROOT, free_port, run, service, stop_process


def image_bytes() -> bytes:
    """构造超过 1 MiB 的有效 PNG，避免把无效图片当成上传通过。"""

    def chunk(kind: bytes, content: bytes) -> bytes:
        return (
            struct.pack("!I", len(content))
            + kind
            + content
            + struct.pack("!I", zlib.crc32(kind + content))
        )

    rows = b"".join(b"\0" + os.urandom(800 * 3) for _ in range(800))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 800, 800, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize("tls", [False, True])
def test_proxy_template(tmp_path, isolated_env, tls_files, tls):
    """同一模板通过七项自检，合法图片到后端，异常日志不含查询凭据。"""
    nginx = os.getenv("NGINX_BINARY") or shutil.which("nginx")
    if not nginx:
        pytest.skip("需要 NGINX_BINARY 或 PATH 中的 nginx；CI Linux 安装真实 Nginx")
    prefix = tmp_path / "nginx"
    (prefix / "logs").mkdir(parents=True)
    (prefix / "temp").mkdir()
    front = free_port()
    token = isolated_env["API_TOKEN"]
    with service(tmp_path, isolated_env) as (backend, process):
        config = (ROOT / "deploy/nginx/idp.conf").read_text(encoding="utf-8")
        config = config.replace("127.0.0.1:8080", f"127.0.0.1:{front}")
        config = config.replace("http://127.0.0.1:8001", backend)
        config = config.replace("/var/log/nginx/idp-access.log", "logs/access.log")
        config = config.replace("/dev/null", "NUL" if os.name == "nt" else "/dev/null")
        verify = True
        scheme = "http"
        if tls:
            cert, key = tls_files
            config = config.replace(
                f"listen 127.0.0.1:{front};",
                f"listen 127.0.0.1:{front} ssl;\n"
                f'    ssl_certificate "{cert.as_posix()}";\n'
                f'    ssl_certificate_key "{key.as_posix()}";',
            )
            verify = ssl.create_default_context(cafile=str(cert))
            scheme = "https"
        (prefix / "nginx.conf").write_text(
            "worker_processes 1;\npid logs/nginx.pid;\nerror_log logs/startup.log;\nevents { worker_connections 128; }\nhttp {\n"
            "client_body_temp_path temp/body; proxy_temp_path temp/proxy;\n"
            "fastcgi_temp_path temp/fastcgi; uwsgi_temp_path temp/uwsgi; scgi_temp_path temp/scgi;\n"
            + config
            + "\n}\n",
            encoding="utf-8",
        )
        command = [nginx, "-p", prefix.as_posix() + "/", "-c", "nginx.conf"]
        syntax = run(command + ["-t"], isolated_env)
        assert syntax.returncode == 0, syntax.stderr
        with (prefix / "console.log").open("w") as output:
            proxy = subprocess.Popen(
                command + ["-g", "daemon off;"],
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_FLAGS,
                start_new_session=os.name != "nt",
            )
            base = f"{scheme}://127.0.0.1:{front}"
            try:
                with httpx.Client(
                    base_url=base, verify=verify, trust_env=False, timeout=10
                ) as client:
                    for _ in range(100):
                        try:
                            if client.get("/api/health").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Nginx 启动超时")
                    check = [
                        sys.executable,
                        ROOT / "scripts/check_deployment.py",
                        base,
                        "--exercise",
                    ]
                    if tls:
                        check += ["--ca-file", tls_files[0]]
                    result = run(check, isolated_env)
                    assert result.returncode == 0, result.stdout + result.stderr
                    assert "14/14" in result.stdout
                    png = image_bytes()
                    assert len(png) > 1024 * 1024
                    response = client.post(
                        "/api/courses/parse-image",
                        headers={"X-API-Key": token},
                        files={"image": ("test.png", png, "image/png")},
                    )
                    # 明确未配置模型的 503，证明穿过代理并到达后端；不是模型识别验收。
                    assert response.status_code == 503 and "detail" in response.json()
                    response = client.post(
                        "/api/courses/parse-image",
                        params={"token": token},
                        headers={"X-API-Key": token},
                        content=b"x" * (12 * 1024 * 1024),
                    )
                    assert response.status_code == 413
                    stop_process(process)
                    response = client.get("/ws", params={"token": token})
                    assert response.status_code == 502
                    failure = run(check, isolated_env)
                    assert failure.returncode != 0 and "PASS WS" not in failure.stdout
            finally:
                run(command + ["-s", "quit"], isolated_env)
                try:
                    proxy.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    stop_process(proxy)
        access = (prefix / "logs/access.log").read_text(encoding="utf-8")
        assert all(str(status) in access for status in (101, 413, 502))
        for log in prefix.rglob("*.log"):
            content = log.read_text(encoding="utf-8", errors="replace")
            assert token not in content and quote(token, safe="") not in content
            assert "?token=" not in content
