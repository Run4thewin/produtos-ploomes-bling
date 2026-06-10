param(
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& .\.venv\Scripts\pip install -r requirements-local.txt -q

$inUse = netstat -ano | Select-String "127.0.0.1:$Port\s+.*LISTENING"
if ($inUse) {
    $pid = ($inUse -split "\s+")[-1]
    Write-Host "Porta $Port em uso pelo PID $pid. Encerrando processo anterior..."
    taskkill /PID $pid /F | Out-Null
    Start-Sleep -Seconds 1
}

Write-Host "Iniciando API em http://127.0.0.1:$Port"
Write-Host "Health: http://127.0.0.1:$Port/health"
Write-Host "Docs:   http://127.0.0.1:$Port/docs"
Write-Host ""
Write-Host "Outra porta: .\scripts\start_local.ps1 -Port 8081"

& .\.venv\Scripts\uvicorn app.main:app --reload --host 127.0.0.1 --port $Port
