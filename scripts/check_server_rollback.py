"""在隔离副本中验证历史代码/schema 回滚，不读取生产库或修改运行服务。"""

import argparse
import importlib.util
import io
import json
import os
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener


def git(repo: Path, *args: str) -> bytes:
    """只查询 Git 对象，不切换分支或更新工作树。"""
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError("所需 Git 对象不可用；保留当前部署，先检查仓库历史")
    return result.stdout


def revision(repo: Path, ref: str) -> str:
    value = git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
    value = value.decode("ascii").strip()
    if len(value) not in {40, 64} or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("Git 版本解析失败")
    return value


def snapshot(repo: Path, ref: str, destination: Path) -> None:
    """只提取 backend/app 普通源码文件；禁止带入配置、数据及链接。"""
    archive = git(repo, "archive", "--format=tar", ref, "--", "backend/app")
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        for member in tree.getmembers():
            if not member.isfile():
                continue
            path = Path(member.name)
            if not member.name.startswith("backend/app/") or ".." in path.parts:
                raise ValueError("源码归档路径不合法")
            if path.name.startswith(".env") or path.suffix in {".db", ".sqlite", ".sqlite3"}:
                raise ValueError("源码归档不应包含私有配置或数据库")
            output = (destination / path).resolve()
            if not output.is_relative_to(destination.resolve()):
                raise ValueError("源码归档越界")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(tree.extractfile(member).read())


def schema(path: Path) -> tuple[list[int], list[str]]:
    """只读检查本轮临时数据库的迁移版本。"""
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        return (
            [
                row[0]
                for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")
            ],
            [row[1] for row in db.execute("PRAGMA table_info(reminders)")],
        )


def api(base: str, token: str, path: str, data: dict | None = None):
    """仅访问临时回环端口；不使用系统代理，不打印鉴权头。"""
    body = json.dumps(data).encode() if data is not None else None
    request = Request(
        base + path,
        data=body,
        headers={"X-API-Key": token, "Content-Type": "application/json"},
    )
    with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
        return response.status, json.load(response)


def stop(process: subprocess.Popen) -> None:
    """只停止本脚本新建的测试进程树。"""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


@contextmanager
def service(source: Path, database: Path, token: str, output: Path):
    """单 worker 临时服务，固定回环并显式禁用微信、模型和调度。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    if port in {80, 443, 8001, 8080}:
        raise ValueError("拒绝使用部署端口")
    env = dict(
        os.environ,
        API_TOKEN=token,
        DB_PATH=str(database),
        WX_ENABLED="false",
        WX_APPID="",
        WX_SECRET="",
        WX_TEMPLATE_ID="",
        LLM_API_KEY="",
        LLM_BASE_URL="",
        LLM_VISION_MODEL="",
        SCHEDULER_ENABLED="false",
        SCHEDULER_INTERVAL_SECONDS="1",
        PYTHONUTF8="1",
    )
    base = f"http://127.0.0.1:{port}"
    with output.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                str(source / "backend"),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--workers",
                "1",
                "--log-level",
                "warning",
            ],
            cwd=source,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("测试服务退出；检查本轮私有目录中的日志")
                try:
                    if api(base, token, "/api/health") == (200, {"status": "ok"}):
                        break
                except OSError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("测试服务健康检查超时")
            yield base
        finally:
            stop(process)


def exercise(repo: Path, previous: str, current: str, directory: Path) -> dict:
    """旧库 v1 → 当前 v2 → 恢复副本并以旧代码启动，保留升级库。"""
    spec = importlib.util.spec_from_file_location(
        "c4_backup", repo / "scripts/backup_backend_db.py"
    )
    backup_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backup_module)
    old = directory / "previous-release"
    new = directory / "current-release"
    snapshot(repo, previous, old)
    snapshot(repo, current, new)
    token = secrets.token_hex(32)
    database = directory / "exercise.db"
    with service(old, database, token, directory / "before.log") as base:
        status, seed = api(base, token, "/api/tasks", {"title": "c4-before-upgrade"})
        if status != 201:
            raise RuntimeError("历史版本测试写入失败")
    before = schema(database)
    if before[0] != [1] or "wechat_user_id" in before[1]:
        raise RuntimeError("历史版本不是预期的 B2 schema 1")
    backup = directory / "before-upgrade.db"
    backup_module.backup_database(database, backup)
    with service(new, database, token, directory / "after.log") as base:
        if seed not in api(base, token, "/api/tasks")[1]:
            raise RuntimeError("升级后原记录缺失")
        status, added = api(base, token, "/api/tasks", {"title": "c4-after-upgrade"})
        if status != 201:
            raise RuntimeError("新版本测试写入失败")
    after = schema(database)
    if after[0] != [1, 2] or "wechat_user_id" not in after[1]:
        raise RuntimeError("没有验证到真实 schema 1→2 迁移")
    restored = directory / "restored.db"
    backup_module.backup_database(backup, restored)
    if schema(restored) != before:
        raise RuntimeError("恢复副本结构不匹配")
    with service(old, restored, token, directory / "restored.log") as base:
        if api(base, token, "/api/tasks")[1] != [seed]:
            raise RuntimeError("旧版本无法读回备份时的数据")
    if schema(database) != after:
        raise RuntimeError("升级后的测试原库发生非预期变化")
    return {
        "passed": True,
        "previous_ref": previous[:7],
        "current_ref": current[:7],
        "schema_before": before[0],
        "schema_after": after[0],
        "old_code_reads_restored_data": True,
        "post_backup_row_excluded": added["id"] != seed["id"],
        "upgraded_copy_preserved": True,
        "production_database_opened": False,
        "production_service_changed": False,
        "directory": str(directory),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--previous-ref", default="5ff462f")
    parser.add_argument("--current-ref", default="HEAD")
    parser.add_argument("--output-parent", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    previous = revision(repo, args.previous_ref)
    current = revision(repo, args.current_ref)
    matches = subprocess.run(
        ["git", "-C", str(repo), "diff", "--quiet", current, "--", "backend/app"],
        capture_output=True,
    )
    if matches.returncode:
        raise ValueError("backend/app 与指定版本不一致；先核对部署版本，不自动覆盖")
    parent = args.output_parent.resolve() if args.output_parent else None
    if parent is not None and not parent.is_dir():
        raise ValueError("输出父目录必须已存在")
    directory = Path(tempfile.mkdtemp(prefix="c4-rollback-drill-", dir=parent)).resolve()
    if os.name != "nt":
        directory.chmod(0o700)
    report = {"passed": False, "directory": str(directory)}
    try:
        report = exercise(repo, previous, current, directory)
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["note"] = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "检查私有日志"
    (directory / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(json.dumps({"passed": False, "preflight_error": str(error)}, ensure_ascii=False))
        raise SystemExit(1)
