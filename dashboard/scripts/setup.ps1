$ErrorActionPreference = 'Stop'
$dashboardRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $dashboardRoot
$env:PIP_CACHE_DIR = Join-Path $dashboardRoot '.cache\pip'
$env:npm_config_cache = Join-Path $dashboardRoot '.cache\npm'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & python -B -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Dashboard virtual environment creation failed.' }
}
& .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r backend\requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dashboard Python dependency installation failed.' }
Set-Location (Join-Path $dashboardRoot 'frontend')
& npm.cmd ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Dashboard frontend dependency installation failed.' }
Write-Host 'Dashboard dependencies installed separately from the trading environment.'
