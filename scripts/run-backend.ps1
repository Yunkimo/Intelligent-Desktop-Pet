# Windows bootstrap. See docs/deploy.md. Native failures must remain failures.
param(
    [ValidateRange(1, 65535)][int]$Port = 8001,
    [Nullable[double]]$Interval = $null,
    [string]$BindAddress = '127.0.0.1'
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Venv = Join-Path $Backend '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $Python)) {
    python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$Requirements = Join-Path $Backend 'requirements.txt'
$Marker = Join-Path $Venv '.deps-sha256'
$Digest = & $Python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" $Requirements
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$Digest = $Digest.Trim()
$Installed = if (Test-Path -LiteralPath $Marker) { (Get-Content -Raw -LiteralPath $Marker).Trim() } else { '' }
if ($Installed -ne $Digest) {
    & $Python -m pip install --disable-pip-version-check -r $Requirements
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Set-Content -LiteralPath $Marker -Value $Digest -Encoding ASCII
}
$EnvFile = Join-Path $Backend '.env'
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Copy-Item -LiteralPath (Join-Path $Backend '.env.example') -Destination $EnvFile
    Write-Warning 'Created backend/.env. Set API_TOKEN before restarting.'
    exit 1
}
$RunArgs = @((Join-Path $PSScriptRoot 'run_backend.py'), '--port', "$Port", '--host', $BindAddress)
if ($null -ne $Interval) { $RunArgs += @('--interval', $Interval.ToString([cultureinfo]::InvariantCulture)) }
& $Python @RunArgs
exit $LASTEXITCODE
