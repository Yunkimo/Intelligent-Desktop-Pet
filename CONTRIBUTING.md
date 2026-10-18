# 贡献指南

## 代码风格

- 统一使用 [Ruff](https://docs.astral.sh/ruff/) 检查与格式化（配置见 `pyproject.toml`）。
- 行宽 ≤ 100；启用规则 `E`/`F`/`I`/`W`（忽略 E501 由 ruff-format 处理）。
- 所有函数/方法使用类型注解；模块职责单一。

```bash
ruff check .            # 静态检查
ruff format .           # 格式化
```

## 提交规范（Conventional Commits）

提交信息统一为 `type(scope): imperative summary`，一个提交只做一件事。Issue、PR 说明和项目文档使用中文。

| type | 用途 |
|---|---|
| feat | 新功能 |
| fix | 修复缺陷 |
| refactor | 重构（不改行为） |
| test | 测试 |
| docs | 文档 |
| ci | CI/构建脚本 |
| chore | 杂项（脚手架、依赖） |

scope 表示改动所属模块，取以下固定值：

| scope | 含义 |
|---|---|
| pet | 桌宠端 |
| backend | 后端 |
| miniprogram | 小程序 |
| repo | 仓库级（脚手架、文档、CI 等跨模块改动） |

示例：`feat(backend): add authenticated websocket broadcasts`、`fix(backend): prevent duplicate reminder claims`、`docs(repo): document deployment steps`。

## 分支与协作流程

1. 检查工作区与已有分支，保留未提交改动；从 `develop` 拉取最新代码（仅快进）。
2. 创建功能分支：`git checkout -b feat/xxx`。
3. 开发并按上面的规范提交。
4. 关联已有 Issue，推送到远端并创建以 `develop` 为目标的 **Pull Request**，通过 CI 与至少一名其他成员评审后合并。`main` 保留验收版本。

## 测试要求

- 新增或修改逻辑必须补充/更新对应单元测试。
- 提交前本地跑通：`ruff check . && pytest`。

## 本地开发

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

## 后端开发与提交检查

在仓库根目录（PowerShell）执行：

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/Activate.ps1
python -m pip install -r backend/requirements-dev.txt
python -m pre_commit install
python -m ruff check .
python -m ruff format --check .
python -m pytest -c backend/pytest.ini backend/tests
python scripts/smoke_backend_ws.py
python -m pip_audit -r backend/requirements.txt
```

提交前查看 `git diff`，显式暂存本次任务文件，再查看 `git diff --cached` 并运行
`python -m pre_commit run --all-files`。钩子执行 Ruff、暂存区空白检查和密钥扫描；
必须在已激活且安装后端开发依赖的环境中提交，禁止使用 `--no-verify`。
第三方 `assets/` 与依赖清单不参加密钥启发式扫描；业务源码、配置、测试和文档参加扫描。
.secrets.baseline 仅登记已核实的两处占位值：设计文档 `sk-xxxx`、桌宠测试 `sk-test`。
扫描不向外部服务发送候选密钥验证；基线按文件和内容哈希匹配，不排除整个源文件。
CI 复验这些检查，并运行真实 WebSocket 冒烟与后端依赖审计。

密钥钩子使用 `python -X utf8`：中文 UTF-8 源文件在 Windows 默认本地编码下可能漏扫，
固定编码以保持与 Linux CI 一致。明确的测试假值仅在对应行注明 allowlist 原因，禁止排除整个测试文件。

后端运行依赖锁定在 `backend/requirements.txt`（包含跨平台环境标记）。升级时修改
`backend/requirements.in`，使用 `uv==0.13.0` 重新生成并复验：

```powershell
uv pip compile --universal --python-version 3.10 backend/requirements.in -o backend/requirements.txt
```

本地 agent 守则放在仓库外，不暂存、不提交、不推送。工作记录、契约与实测证据放入
项目文档；接口与共享配置变更请相关成员评审。仅测试通过不能标记任务已完成。
