# Git + Google Cloud Run

Sim, é possível versionar no Git e fazer deploy automático no Cloud Run a cada push.

## Fluxo

```
GitHub/GitLab  →  push na branch main  →  Cloud Build Trigger  →  cloudbuild.yaml  →  Cloud Run
```

---

## 1. Versionar no Git (local)

```powershell
cd c:\Users\CMC_DEV_001\Documents\projetos\ploomes_bling_produtos
git init
git add .
git commit -m "Initial commit: sync produtos Bling-Ploomes"
```

Arquivos **não** versionados (`.gitignore`): `.env`, `tokens.json`, `.venv/`

---

## 2. Criar repositório remoto

**GitHub (recomendado):**

1. Crie um repo vazio no GitHub (ex: `ploomes-bling-produtos`)
2. Conecte:

```powershell
git remote add origin https://github.com/Run4thewin/produtos-ploomes-bling.git
git branch -M main
git push -u origin main
```

**Alternativa:** Google Cloud Source Repositories

```powershell
gcloud source repos create ploomes-bling-produtos
git remote add google https://source.developers.google.com/p/SEU_PROJETO/r/ploomes-bling-produtos
git push google main
```

---

## 3. Setup GCP (uma vez)

```powershell
$PROJECT_ID = "seu-projeto-gcp"
$REGION = "us-central1"

.\deploy\setup.ps1 -ProjectId $PROJECT_ID -Region $REGION
```

Criar secrets, enviar `tokens.json` para GCS — ver README.md seção deploy.

---

## 4. Conectar Git ao Cloud Build (deploy automático)

### Opção A — Console (mais simples)

1. [Cloud Run](https://console.cloud.google.com/run) → **Create service** → **Continuously deploy from a repository**
2. Conecte GitHub/GitLab
3. Selecione o repositório e branch `main`
4. Build type: **Dockerfile** (ou Cloud Build configuration → `cloudbuild.yaml`)
5. Service name: `ploomes-bling-sync`
6. Region: `us-central1`
7. Configure variáveis de ambiente e secrets

### Opção B — gcloud (trigger manual)

Após conectar o repositório no Console (Cloud Build → Repositories):

```powershell
gcloud builds triggers create github `
  --name="ploomes-bling-deploy-main" `
  --repo-name="produtos-ploomes-bling" `
  --repo-owner="Run4thewin" `
  --branch-pattern="^main$" `
  --build-config="cloudbuild.yaml" `
  --substitutions="_REGION=us-central1,_REPOSITORY=ploomes-bling,_GCS_BUCKET=SEU_PROJETO-ploomes-bling-tokens,_SERVICE_URL=https://ploomes-bling-sync-xxxxx.run.app,_TASKS_SA=ploomes-bling-tasks@SEU_PROJETO.iam.gserviceaccount.com"
```

A partir daí, **cada push em `main`** dispara build + deploy.

---

## 5. Primeiro deploy via Git

Se ainda não tiver URL do serviço:

1. Faça o primeiro push
2. Aguarde o build no [Cloud Build](https://console.cloud.google.com/cloud-build/builds)
3. Pegue a URL:

```powershell
gcloud run services describe ploomes-bling-sync --region us-central1 --format="value(status.url)"
```

4. Atualize o trigger com `_SERVICE_URL` correta (substitutions)
5. Faça um novo push (ou rode o trigger manualmente)

---

## 6. Deploy manual (sem push)

Ainda funciona com o repo local:

```powershell
gcloud builds submit --config cloudbuild.yaml `
  --substitutions=_GCS_BUCKET=SEU_PROJETO-ploomes-bling-tokens,_SERVICE_URL=https://SEU-SERVICO.run.app,_TASKS_SA=ploomes-bling-tasks@SEU_PROJETO.iam.gserviceaccount.com
```

---

## Checklist pós-deploy

- [ ] Webhook Bling → `{SERVICE_URL}/webhooks/bling`
- [ ] Webhook Ploomes → `{SERVICE_URL}/webhooks/ploomes?validation_key=...`
- [ ] Cloud Scheduler → `/jobs/reconcile` diário
- [ ] `tokens.json` no bucket GCS
- [ ] Escopo `product` no app Bling
