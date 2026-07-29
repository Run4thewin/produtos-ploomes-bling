param(
    [Parameter(Mandatory=$true)]
    [string]$code
)

Write-Host "Trocando code por token Bling..." -ForegroundColor Cyan

& .\.venv\Scripts\python scripts\bling_oauth_manual.py --code $code

if ($LASTEXITCODE -eq 0) {
    Write-Host "Tokens salvos com sucesso!" -ForegroundColor Green
} else {
    Write-Host "Erro ao salvar tokens!" -ForegroundColor Red
    exit 1
}
