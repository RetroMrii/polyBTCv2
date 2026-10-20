param([ValidateSet('all','backend','frontend')][string]$Service = 'all')
$ErrorActionPreference = 'Stop'
$dashboardRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dashboardPython = Join-Path $dashboardRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $dashboardPython)) { throw 'Run dashboard/scripts/setup.ps1 first.' }
if ($Service -eq 'backend') {
    Set-Location (Join-Path $dashboardRoot 'backend')
    & $dashboardPython -B -m uvicorn app.main:app --host 127.0.0.1 --port 8001
    exit $LASTEXITCODE
}
if ($Service -eq 'frontend') {
    Set-Location (Join-Path $dashboardRoot 'frontend')
    $env:npm_config_cache = Join-Path $dashboardRoot '.cache\npm'
    & npm.cmd run dev
    exit $LASTEXITCODE
}
$dashboardLogs = Join-Path $dashboardRoot 'logs'
New-Item -ItemType Directory -Force -Path $dashboardLogs | Out-Null
foreach ($entry in @(@{ Name='backend'; Port=8001 }, @{ Name='frontend'; Port=3000 })) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $entry.Port -ErrorAction SilentlyContinue
    if ($listener) {
        Write-Host "Port $($entry.Port) is already in use; $($entry.Name) was not started."
        continue
    }
    if ($entry.Name -eq 'backend') {
        $launchExecutable = $dashboardPython
        $launchArgs = @('-B', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8001')
        $launchDirectory = Join-Path $dashboardRoot 'backend'
    } else {
        $launchExecutable = (Get-Command node.exe -ErrorAction Stop).Source
        $launchDirectory = Join-Path $dashboardRoot 'frontend'
        Push-Location $launchDirectory
        try {
            & $launchExecutable (Join-Path $launchDirectory 'scripts\build-content.mjs')
            if ($LASTEXITCODE -ne 0) { throw 'Publication content generation failed.' }
        } finally { Pop-Location }
        $launchArgs = @(('"' + (Join-Path $launchDirectory 'node_modules\vite\bin\vite.js') + '"'), '--configLoader', 'runner')
    }
    # Launch the installed runtimes directly. A nested Windows PowerShell can
    # have a different script policy from the shell invoking this launcher.
    $process = Start-Process $launchExecutable -ArgumentList $launchArgs -WindowStyle Hidden -PassThru -WorkingDirectory $launchDirectory -RedirectStandardOutput (Join-Path $dashboardLogs "$($entry.Name).stdout.log") -RedirectStandardError (Join-Path $dashboardLogs "$($entry.Name).stderr.log")
    Write-Host "Started dashboard $($entry.Name) PID $($process.Id). Logs: $dashboardLogs"
}
Write-Host 'Dashboard: http://localhost:3000   API: http://127.0.0.1:8001/api/docs'
Write-Host 'For foreground terminals with Ctrl+C shutdown, run -Service backend and -Service frontend separately.'
