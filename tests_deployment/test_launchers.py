"""从隔离副本执行真实 Windows/Bash 启动入口，验证失败码及目录语义。"""

import hashlib
import os
import shutil
import sys
import sysconfig
import venv
from pathlib import Path

import httpx
import pytest
from conftest import ROOT, free_port, run, service


@pytest.fixture
def launch_copy(tmp_path, isolated_env):
    """复制业务文件，使用独立轻量 venv；测试依赖由已安装环境提供。"""
    root = tmp_path / "source with spaces"
    shutil.copytree(
        ROOT / "backend/app", root / "backend/app", ignore=shutil.ignore_patterns("__pycache__")
    )
    (root / "scripts").mkdir()
    for name in (
        "run_backend.py",
        "run-backend.ps1",
        "run-backend.sh",
        "reset_demo.py",
        "backup_backend_db.py",
    ):
        shutil.copyfile(ROOT / "scripts" / name, root / "scripts" / name)
    for name in ("requirements.txt", ".env.example"):
        shutil.copyfile(ROOT / "backend" / name, root / "backend" / name)
    venv_path = root / "backend/.venv"
    venv.EnvBuilder(with_pip=False, system_site_packages=True).create(venv_path)
    digest = hashlib.sha256((root / "backend/requirements.txt").read_bytes()).hexdigest()
    (venv_path / ".deps-sha256").write_text(digest)
    env = dict(isolated_env, PYTHONPATH=sysconfig.get_path("purelib"))
    env.pop("DB_PATH", None)
    return root, env


def launcher(root: Path, port: int) -> list[str]:
    """选择当前操作系统的真实入口，不依赖可执行文件位。"""
    if os.name == "nt":
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(root / "scripts/run-backend.ps1"),
            "-Port",
            str(port),
            "-Interval",
            "1",
        ]
    return ["bash", str(root / "scripts/run-backend.sh"), str(port), "1"]


def test_missing_env_and_placeholder(launch_copy, tmp_path):
    """首次复制配置退出非零；示例凭据不会直接启动服务。"""
    root, env = launch_copy
    result = run(launcher(root, free_port()), env, cwd=tmp_path)
    assert result.returncode != 0
    assert (root / "backend/.env").is_file()
    env.pop("API_TOKEN", None)
    result = run(launcher(root, free_port()), env, cwd=tmp_path)
    assert result.returncode != 0
    assert "API_TOKEN" in result.stdout + result.stderr


def test_launcher_port_collision_and_relative_path(launch_copy, tmp_path):
    """工作目录无关；端口冲突必须传出 Uvicorn 非零退出码。"""
    root, env = launch_copy
    (root / "backend/.env").write_text("DB_PATH=data/demo-launch.db\n", encoding="utf-8")
    port = free_port()
    command = launcher(root, port)
    with service(tmp_path, env, args=command, port=port, cwd=tmp_path) as (base, _):
        assert (root / "backend/data/demo-launch.db").is_file()
        assert not (tmp_path / "data/demo-launch.db").exists()
        result = run(command, env, cwd=tmp_path)
        assert result.returncode != 0
        assert "bind" in result.stdout + result.stderr
        assert httpx.get(base + "/api/health", trust_env=False).status_code == 200


def test_reset_cli_confirmation(launch_copy, tmp_path):
    """CLI 默认只预览，且执行前必须显式声明服务已停止。"""
    root, env = launch_copy
    script = root / "scripts/reset_demo.py"
    args = [sys.executable, script, "--database", "backend/data/demo-cli.db"]
    assert run(args + ["--init"], env, cwd=tmp_path).returncode == 0
    path = root / "backend/data/demo-cli.db"
    before = path.read_bytes()
    assert run(args, env, cwd=tmp_path).returncode == 0
    assert run(args + ["--yes"], env, cwd=tmp_path).returncode != 0
    assert path.read_bytes() == before
    assert run(args + ["--yes", "--stopped"], env, cwd=tmp_path).returncode == 0
    assert list((root / "backend/backups").glob("demo-cli-*.db"))


def test_invalid_interval(launch_copy, tmp_path):
    """两个包装入口都应传递显式间隔，并拒绝零间隔。"""
    root, env = launch_copy
    (root / "backend/.env").write_text("DB_PATH=data/demo-invalid.db\n", encoding="utf-8")
    command = launcher(root, free_port())
    command[-1] = "0"
    result = run(command, env, cwd=tmp_path)
    assert result.returncode != 0
    assert "interval" in result.stdout + result.stderr
    assert not (root / "backend/data/demo-invalid.db").exists()
