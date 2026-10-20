# Start backend (port 8000) and frontend (port 5173) together; Ctrl+C stops both.
# Commands come from backend/AGENTS.md and frontend/AGENTS.md (never uvicorn --reload).
# Windows PowerShell 5.1: .\start.ps1  (if execution policy blocks it:
#   powershell -ExecutionPolicy Bypass -File .\start.ps1)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backendUrl = 'http://localhost:8000'
$frontendUrl = 'http://localhost:5173'

# Port check, not an HTTP probe: Invoke-WebRequest to localhost stalls on ::1 vs 127.0.0.1 here.
function Test-Listening($port) {
    [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

foreach ($port in 8000, 5173) {
    if (Test-Listening $port) {
        Write-Error "Port $port is already in use; stop that process first."
    }
}
if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) {
    Write-Error "Frontend not installed: run 'npm install' in frontend\ first."
}

$procs = @()
try {
    $procs += Start-Process -FilePath 'uv' -ArgumentList 'run', 'uvicorn', 'dss.main:app', '--port', '8000' `
        -WorkingDirectory (Join-Path $root 'backend') -NoNewWindow -PassThru
    $procs += Start-Process -FilePath 'npm.cmd' -ArgumentList 'run', 'dev' `
        -WorkingDirectory (Join-Path $root 'frontend') -NoNewWindow -PassThru

    $ready = $false
    for ($i = 0; $i -lt 90; $i++) {
        if ($procs | Where-Object { $_.HasExited }) { break }
        if ((Test-Listening 8000) -and (Test-Listening 5173)) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    $exitCode = 1
    if (-not $ready) {
        Write-Host 'Backend or frontend did not start; see the output above.'
    }
    else {
        Write-Host ''
        Write-Host "Backend:  $backendUrl  (health: $backendUrl/api/health)"
        Write-Host "Frontend: $frontendUrl"
        Write-Host 'Press Ctrl+C to stop both.'

        # If either process exits, stop the other one too.
        while (-not ($procs | Where-Object { $_.HasExited })) { Start-Sleep -Seconds 1 }
        Write-Host 'A process exited.'
    }
}
finally {
    Write-Host ''
    Write-Host 'Stopping backend and frontend...'
    foreach ($p in $procs) {
        if ($p -and -not $p.HasExited) { & taskkill.exe /T /F /PID $p.Id 2>$null | Out-Null }
    }
    Write-Host 'Stopped.'
}
exit $exitCode
