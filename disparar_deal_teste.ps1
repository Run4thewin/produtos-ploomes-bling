# Uso LOCAL apenas. Dispara o webhook do Deal de teste contra o servidor local.
# O servico rebusca o Deal completo na API do Ploomes, entao basta o Id.
# Rode isto em OUTRA janela, com o servidor ja no ar (testar_funil_teste.ps1).

param(
    [long]$DealId = 1107064301
)

$body = @{ EntityId = 2; Id = $DealId } | ConvertTo-Json -Compress

Write-Host "POST /webhooks/ploomes/deals  (Deal $DealId)" -ForegroundColor Cyan
try {
    $resp = Invoke-RestMethod -Method Post `
        -Uri "http://127.0.0.1:8080/webhooks/ploomes/deals" `
        -ContentType "application/json" `
        -Body $body
    $resp | ConvertTo-Json -Depth 10
} catch {
    Write-Host "Falha na chamada:" -ForegroundColor Red
    $_.Exception.Message
    if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message }
}
