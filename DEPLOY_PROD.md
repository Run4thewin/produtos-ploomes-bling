# Deploy em Produção - Token Bling Automático

## 📋 Checklist Rápido

✅ Token renovado localmente  
✅ Código commitado e pushed  
⏳ **Você está aqui** → Deploy em Cloud Run + Cloud Scheduler  

## 🚀 Deploy Cloud Run

O código já foi pushed. Trigger build automaticamente:

```bash
# Opção 1: Build automático (se configurado no Git trigger)
# Apenas fazer push (já feito!)

# Opção 2: Manual (se precisar redeploy imediato)
gcloud builds submit --config cloudbuild.yaml --project seu-gcp-project
```

A app será deployada com o novo endpoint `/jobs/refresh-bling-token`.

---

## ⏰ Configurar Cloud Scheduler (Renovação Automática)

### Pré-requisitos
Você vai precisar de:
- `PROJECT_ID` do GCP
- `SERVICE_URL` da app Cloud Run (ex: `https://produtos-ploomes-bling-abc123.run.app`)
- `INTERNAL_SECRET` (do Secret Manager: `gcloud secrets versions access latest --secret=internal-secret`)

### Passo 1: Obter valores necessários

```bash
# Obter PROJECT_ID
gcloud config get-value project

# Obter SERVICE_URL da app já deployada
gcloud run services describe produtos-ploomes-bling --region us-central1 --format='value(status.url)'

# Obter INTERNAL_SECRET
gcloud secrets versions access latest --secret=internal-secret --project seu-gcp-project
```

### Passo 2: Criar Cloud Scheduler job

```bash
bash setup-cloud-scheduler.sh \
  seu-gcp-project \
  https://produtos-ploomes-bling-abc123.run.app \
  seu-internal-secret-aqui
```

Ou manualmente no [Console GCP](https://console.cloud.google.com/cloudscheduler).

### Passo 3: Testar renovação

```bash
# Testar manualmente (executar agora)
gcloud scheduler jobs run bling-token-refresh \
  --location us-central1 \
  --project seu-gcp-project

# Ver resultado nos logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=produtos-ploomes-bling" \
  --limit 10 \
  --format json \
  --project seu-gcp-project \
  | grep -i "token.*renovado"
```

---

## ✅ Verificação

### Scheduler rodando?
```bash
gcloud scheduler jobs list --location us-central1 --project seu-gcp-project
```

Deve aparecer `bling-token-refresh` com status ativo.

### Token renovando?
Verifique logs da app (deve conter "Access token Bling renovado"):

```bash
gcloud logging read "resource.type=cloud_run_revision" \
  --limit 50 \
  --project seu-gcp-project | grep -i "token.*renovado"
```

---

## 📝 Resumo do que foi implementado

| Componente | Descrição |
|---|---|
| **Endpoint** | `POST /jobs/refresh-bling-token` — renova token on-demand |
| **Scheduler** | Cloud Scheduler — chama endpoint a cada 24h |
| **Tokens** | Salvos em GCS bucket (`bling/tokens.json`) |
| **Renovação automática** | Antes do token expirar (7+ dias) |

Se algo der errado, os logs vão aparecer em Cloud Logging com "invalid_grant" ou similar.

---

## 🆘 Troubleshooting

### "401 Unauthorized" no scheduler
→ Verifique se o OIDC token do Cloud Scheduler está autorizado. Service account precisa de permissão para chamar a app.

### "invalid_grant" nos logs
→ Refresh token foi revogado. Refaça o OAuth manual e faça deploy do novo `tokens.json`.

### Scheduler não executa
→ Verifique timezone e schedule. Teste manualmente com `gcloud scheduler jobs run`.

---

**Última atualização**: 2026-07-29  
**Commit**: 34f795d (Adiciona renovação automática proativa de token Bling)
