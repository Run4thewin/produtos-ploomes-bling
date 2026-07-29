# Renovação Automática de Token Bling

## Problema
O refresh token do Bling foi revogado (erro `invalid_grant`), causando falha na renovação automática de tokens.

## Solução Implementada

### 1. Endpoint Novo
Adicionado `/jobs/refresh-bling-token` que renova o access token proativamente.

### 2. Resolver Agora (One-time)
Execute para fazer novo OAuth:

```powershell
.\.venv\Scripts\python scripts\bling_oauth_manual.py
```

Abra a URL gerada, autorize no Bling e copie o `code`. Depois execute:

```powershell
.\.venv\Scripts\python scripts\bling_oauth_manual.py --code "SEU_CODE"
```

Isso gera novo `tokens.json` com access_token + refresh_token válidos.

### 3. Renovação Automática Proativa

Para **nunca** expirar novamente, configure um scheduler que chama `/jobs/refresh-bling-token` a cada 24 horas.

#### Opção A: Cloud Scheduler (Produção)

1. No Console GCP, vá para **Cloud Scheduler**
2. Crie novo job "bling-token-refresh"
3. Configure:
   - **Frequency**: `0 3 * * *` (3 AM diariamente)
   - **HTTP Target**: POST `https://seu-service.run.app/jobs/refresh-bling-token`
   - **Auth Header**: `x-internal-secret: ${INTERNAL_SECRET}`

#### Opção B: APScheduler (Desenvolvimento Local)

Se quiser scheduler local, edite `app/main.py`:

```python
from apscheduler.schedulers.background import BackgroundScheduler

def refresh_bling_token_background():
    try:
        bling = BlingClient(get_settings())
        bling.force_refresh_access_token()
        logger.info("Token Bling renovado via scheduler background")
    except Exception as exc:
        logger.exception("Erro ao renovar token Bling via scheduler background: %s", exc)

scheduler = BackgroundScheduler()
scheduler.add_job(refresh_bling_token_background, "interval", hours=24)
scheduler.start()

@app.on_event("startup")
async def startup_event():
    if not scheduler.running:
        scheduler.start()

@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()
```

#### Opção C: Teste Manual Local

```powershell
$uri = "http://localhost:8000/jobs/refresh-bling-token"
$header = @{"x-internal-secret" = "seu-secret-aqui"}
Invoke-WebRequest -Uri $uri -Method Post -Headers $header
```

### 4. Como Funciona

- **BlingClient._has_valid_access_token()**: Verifica se token expira em menos de 5 minutos
- **force_refresh_access_token()**: Chama `/oauth/token` com `grant_type=refresh_token`
- **Token Store**: Salva access_token, refresh_token e expires_at em `tokens.json` (ou GCS)
- **Scheduler**: Renova a cada 24h antes de expirar (tokens duram ~7 dias)

### 5. Monitoramento

Verifique logs da app para confirmar renovação:

```
Access token Bling renovado via job schedule
```

Se vir `invalid_grant`, o refresh token foi revogado novamente → refaça o OAuth manual.

---

**Data de implementação**: 2026-07-29  
**Commit**: (será criado após testes)
