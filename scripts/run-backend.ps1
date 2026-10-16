# 后端启动脚本（Windows 本地开发路线，见 docs/deploy.md）。
# 用法：powershell -ExecutionPolicy Bypass -File scripts\run-backend.ps1 [-Port 8001] [-Interval 30]
# 首次运行自动创建 backend/.venv 并安装依赖；缺少 backend/.env 时从示例复制并提醒填写 API_TOKEN。
param(
    [int]$Port = 8001,
    [int]$Interval = 30
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Venv = Join-Path $Backend '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'

if (-not (Test-Path $Python)) {
    Write-Host '[run-backend] 创建虚拟环境 backend/.venv ...'
    python -m venv $Venv
}

$Marker = Join-Path $Venv '.deps-installed'
if (-not (Test-Path $Marker)) {
    Write-Host '[run-backend] 安装依赖 ...'
    & $Python -m pip install --disable-pip-version-check -q -r (Join-Path $Backend 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
    New-Item -ItemType File -Path $Marker | Out-Null
}

$EnvFile = Join-Path $Backend '.env'
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Backend '.env.example') $EnvFile
    Write-Warning '[run-backend] 已从 .env.example 复制 backend/.env，请填入 API_TOKEN 后重新运行'
    exit 1
}

$Env:SCHEDULER_INTERVAL_SECONDS = "$Interval"
Write-Host "[run-backend] 启动后端：http://0.0.0.0:$Port（单 worker，调度扫描 $Interval 秒）"
& $Python -m uvicorn app.main:app --app-dir $Backend --host 0.0.0.0 --port $Port --workers 1
