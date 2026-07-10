# Ploomes ↔ Bling — Sincronização de Produtos (Cloud Run)

Sincroniza produtos entre **Bling** e **Ploomes** em duas direções:

```
Bling (webhook)  → /webhooks/bling   → cria/atualiza no Ploomes
Ploomes (webhook)→ /webhooks/ploomes → cria no Bling se nao existir
Ploomes (Deal)   → /webhooks/ploomes/deals → cria pedido de venda no Bling
Cloud Scheduler  → /jobs/reconcile  → corrige divergencias Bling → Ploomes
```

## Componentes

| Endpoint | Função |
|---|---|
| `POST /webhooks/bling` | Bling → Ploomes: valida HMAC, enfileira |
| `POST /webhooks/ploomes?validation_key=...` | Ploomes → Bling: cria produto se nao existir |
| `POST /webhooks/ploomes/deals?validation_key=...` | Ploomes Deal → Bling: cria pedido de venda |
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
| `marca` | `Name` + campo Fabricante | Nao |
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

## Ploomes Deal → Pedido Bling (webhook)

Quando um Deal chega a um stage configurado, o servico processa apenas esse Deal, busca a ultima Quote, cria um pedido de venda no Bling e move o Deal para o stage de destino.

Endpoint:

```text
https://produtos-ploomes-bling-539366668006.us-central1.run.app/webhooks/ploomes/deals?validation_key=cmc-ploomes-bling-webhook
```

Registrar webhook no Ploomes:

```powershell
.\.venv\Scripts\python scripts\register_ploomes_deal_webhook.py `
  --callback-url "https://produtos-ploomes-bling-539366668006.us-central1.run.app/webhooks/ploomes/deals?validation_key=cmc-ploomes-bling-webhook" `
  --validation-key "cmc-ploomes-bling-webhook" `
  --actions update
```

O fluxo usa `PLOOMES_DEAL_STAGE_RULES` no formato `pipeline:stage_origem:stage_destino`. Por padrao, foram migradas as regras do robo legado:

```text
110005492:110022662:110022663,110001615:110020807:110008939
```

Para evitar duplicidade, o servico verifica o campo `PLOOMES_DEAL_ORDER_FIELD` antes de criar o pedido. Se ja houver uma referencia de pedido Bling, o webhook retorna `already_processed`.

## Pontos de atenção

- **Cloud Tasks** é obrigatório em produção: o webhook responde em <5s e o processamento ocorre de forma assíncrona.
- **Deal → Pedido Bling** processa direto no webhook, sem Cloud Tasks, conforme decisao de manter esse fluxo mais simples.
- **Tokens Bling** são persistidos no GCS; a cada refresh o arquivo é atualizado automaticamente.
- **Cota diária Bling**: a API v3 permite ~120.000 requisições/dia. O `BlingClient` respeita um orçamento diário (`BLING_DAILY_REQUEST_BUDGET`, padrão 100.000) persistido em `.bling_quota.json` (ou no GCS em produção), resetado à meia-noite (UTC). Ao atingir o limite, o `blng_fetcher` **para de forma limpa e salva o progresso**. Como o backfill (`--entity nfe-detail`) e as listagens pulam registros já gravados, basta **reexecutar no dia seguinte** para continuar. Ex.: 240 mil itens que exigem 1 requisição de detalhe cada levam ~3 dias sob o orçamento de 100 mil/dia — não há endpoint de detalhe em lote no Bling, então dividir por dias é a única forma de não estourar a cota.
- **Exclusão no Bling** inativa o produto no Ploomes (`Suspended=true`), não apaga.
- Amplie `app/services/mapping.py` e `diff_fields` conforme novos campos forem necessários.
