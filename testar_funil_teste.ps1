# Uso LOCAL apenas. Sobe o servico local lendo TODA a config do .env.
# (As variaveis de teste do Funil de Teste ja estao no .env -- nao setar aqui,
#  senao a env de sessao sobrescreve o .env, que foi o bug do situacao=0.)
# NAO altera app/config.py -- o prod continua intocado.

Write-Host "Servidor: http://127.0.0.1:8080   (Ctrl+C para parar)" -ForegroundColor Cyan
Write-Host "Config carregada do .env. Logs em: .\logs_teste_funil.txt" -ForegroundColor Yellow
Write-Host "Dispare em outra janela:  .\disparar_deal_teste.ps1" -ForegroundColor Yellow
Write-Host ""

python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 2>&1 | Tee-Object -FilePath ".\logs_teste_funil.txt"
