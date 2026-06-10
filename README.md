# Ploomes ↔ Bling — Sincronização de Produtos (Cloud Run)

Sincroniza produtos entre **Bling** e **Ploomes** em duas direções:

```
Bling (webhook)  → /webhooks/bling   → cria/atualiza no Ploomes
Ploomes (webhook)→ /webhooks/ploomes → cria no Bling se nao existir
Cloud Scheduler  → /jobs/reconcile  → corrige divergencias Bling → Ploomes
```

## Componentes

| Endpoint | Função |
|---|---|
| `POST /webhooks/bling` | Bling → Ploomes: valida HMAC, enfileira |
| `POST /webhooks/ploomes?validation_key=...` | Ploomes → Bling: cria produto se nao existir |
| `POST /tasks/process-bling-product` | Worker Bling → Ploomes |
| `POST /tasks/process-ploomes-product` | Worker Ploomes → Bling |
| `POST /jobs/full-sync` | Carga inicial Bling → Ploomes |
| `POST /jobs/reconcile` | Reconciliacao Bling → Ploomes |
| `GET /health` | Health check |

## Credenciais (projeto legado)

Este serviço reutiliza as configurações de:

`c:\Users\CMC_DEV_001\Documents\projetos\cmc\automacao\ploomes_bling`

| Variável | Origem no projeto legado |
|---|---|
| `BLING_CLIENT_ID` / `BLING_CLIENT_SECRET` | `get_autorization_token_bling.py` |
| `PLOOMES_USER_KEY` | `ploomes_bling.py` → `headers['user-key']` |
| `BLING_TOKENS_PATH` | `tokens.json` (arquivo compartilhado) |
| `LEGACY_PLOOMES_BLING_PATH` | fallback OAuth Selenium se o refresh falhar |

O `.env` já vem preenchido com esses valores. O `tokens.json` é **compartilhado** com o projeto legado — quando um serviço renova o token, o outro também enxerga.

## Pré-requisitos

1. App Bling API v3 com escopo **`product`** e webhooks configurados
2. Usuário de integração no Ploomes com `User-Key` (já configurado)
3. `PLOOMES_GROUP_ID=1100000674` ("Grupo de produtos 1")
4. OAuth Bling já realizado no projeto legado (`tokens.json`)

## Desenvolvimento local

```powershell
cd c:\Users\CMC_DEV_001\Documents\projetos\ploomes_bling_produtos
.\scripts\start_local.ps1
```

Ou passo a passo:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-local.txt

# Se o token Bling expirou:
.\scripts\refresh_bling_token.ps1

# API local
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

Endpoints locais:

| URL | Uso |
|---|---|
| http://127.0.0.1:8080/health | Health check |
| http://127.0.0.1:8080/docs | Swagger |
| `POST /jobs/reconcile` | Header `X-Internal-Secret` do `.env` |
| `POST /jobs/full-sync` | Carga inicial |

Com `USE_CLOUD_TASKS=false`, o webhook processa direto (útil para testes locais).

### Escopo Bling obrigatório

O app Bling precisa do escopo **`product`** (Produtos). Sem isso a API retorna `403 insufficient_scope`.
No [developer.bling.com.br](https://developer.bling.com.br), adicione o escopo ao app e rode `.\scripts\refresh_bling_token.ps1` para reautorizar.

## Deploy no Google Cloud Run

### 1. Setup GCP (uma vez)

```powershell
.\deploy\setup.ps1 -ProjectId "SEU_PROJETO"
```

### 2. Secrets

```powershell
echo -n "CLIENT_ID" | gcloud secrets create bling-client-id --data-file=-
echo -n "CLIENT_SECRET" | gcloud secrets create bling-client-secret --data-file=-
echo -n "USER_KEY" | gcloud secrets create ploomes-user-key --data-file=-
echo -n "SEGREDO_FORTE" | gcloud secrets create internal-secret --data-file=-
```

### 3. Tokens Bling no GCS

```powershell
gsutil cp tokens.json gs://SEU_PROJETO-ploomes-bling-tokens/bling/tokens.json
```

### 4. Build e deploy

```powershell
gcloud builds submit --config cloudbuild.yaml `
  --substitutions=_PLOOMES_GROUP_ID=12345,_GCS_BUCKET=SEU_PROJETO-ploomes-bling-tokens,_SERVICE_URL=https://ploomes-bling-sync-xxxxx.run.app,_TASKS_SA=ploomes-bling-tasks@SEU_PROJETO.iam.gserviceaccount.com
```

### 5. Webhook no Bling

No app Bling → Webhooks:

- **URL:** `https://SEU-SERVICO.run.app/webhooks/bling`
- **Recurso:** `product`
- **Ações:** created, updated, deleted

### 6. Cloud Scheduler (reconciliação diária)

```powershell
gcloud scheduler jobs create http ploomes-bling-reconcile `
  --location=us-central1 `
  --schedule="0 3 * * *" `
  --uri="https://SEU-SERVICO.run.app/jobs/reconcile" `
  --http-method=POST `
  --headers="X-Internal-Secret=SEU_SEGREDO"
```

### 7. Carga inicial (uma vez, após deploy)

```powershell
curl -X POST https://SEU-SERVICO.run.app/jobs/full-sync `
  -H "X-Internal-Secret: SEU_SEGREDO"
```

## Mapeamento de campos

Produto no Bling que **não existe** no Ploomes → **criado** automaticamente.

| Bling | Ploomes | Obrigatório |
|---|---|---|
| `marca` | `Name` + campo Fabricante | Sim |
| `codigo` | `Code` + campo Partnumber | Sim |
| `descricaoCurta` | `Name` | Sim |
| `preco` | `UnitPrice` | Sim |
| `situacao` (A/I) | `Suspended` | — |
| `tributacao.ncm` | campo NCM | Não |
| `pesoLiquido` / `pesoBruto` | campo Descrição do Produto | Não |
| `dimensoes.*` | campo Descrição do Produto | Não |

**Nome (Ploomes e Bling):** `fabricante + partnumber + breve descrição`

Exemplo: `SCHNEIDER ABC123 Disjuntor monopolar 20A`

## Ploomes → Bling (webhook)

Quando um produto e criado/atualizado no Ploomes e **nao existe no Bling** (por `Code`), o servico cria no Bling com o mesmo formato.

Registrar webhook no Ploomes:

```powershell
.\.venv\Scripts\python scripts\register_ploomes_webhook.py `
  --callback-url "https://SEU-SERVICO/webhooks/ploomes?validation_key=cmc-ploomes-bling-webhook" `
  --validation-key "cmc-ploomes-bling-webhook" `
  --actions create,update
```

Recomendacao: registrar apenas `create` para evitar loop de atualizacoes entre os dois sistemas.

## Pontos de atenção

- **Cloud Tasks** é obrigatório em produção: o webhook responde em <5s e o processamento ocorre de forma assíncrona.
- **Tokens Bling** são persistidos no GCS; a cada refresh o arquivo é atualizado automaticamente.
- **Exclusão no Bling** inativa o produto no Ploomes (`Suspended=true`), não apaga.
- Amplie `app/services/mapping.py` e `diff_fields` conforme novos campos forem necessários.
