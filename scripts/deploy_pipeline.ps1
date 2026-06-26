# =============================================================================
# deploy_pipeline.ps1
# Deploy do Bling Pipeline no Google Cloud Run Jobs + Cloud Scheduler
#
# Pré-requisitos:
#   - gcloud CLI instalado e autenticado (gcloud auth login)
#   - Docker Desktop rodando
#   - tokens.json válido em $TOKENS_LOCAL_PATH
#
# Executar da pasta raiz do projeto:
#   .\scripts\deploy_pipeline.ps1
# =============================================================================

# ---------------------------------------------------------------------------
# VARIÁVEIS — ajuste se necessário
# ---------------------------------------------------------------------------
$PROJECT      = "portal-cmc-442413"
$REGION       = "us-central1"
$JOB_NAME     = "bling-pipeline"
$SA_NAME      = "bling-scheduler"                      # service account do Cloud Scheduler
$REPO         = "bling-pipeline"                       # Artifact Registry repo
$IMAGE        = "$REGION-docker.pkg.dev/$PROJECT/$REPO/$JOB_NAME`:latest"
$GCS_BUCKET   = "$PROJECT-bling"                      # bucket para tokens OAuth
$TOKENS_LOCAL = "tokens.json"                          # tokens.json local (já autorizado)
$SCHEDULE     = "0 * * * *"                            # toda hora em ponto (UTC)

# Segredos criados no Secret Manager
$SECRET_DB_PASS   = "bling-db-password"
$SECRET_SA_JSON   = "bling-sa-json"
$SECRET_BLING_SEC = "bling-client-secret"

# ---------------------------------------------------------------------------
# 1. Habilitar APIs necessárias
# ---------------------------------------------------------------------------
Write-Host "`n[1/9] Habilitando APIs..." -ForegroundColor Cyan
gcloud services enable `
    run.googleapis.com `
    cloudscheduler.googleapis.com `
    artifactregistry.googleapis.com `
    secretmanager.googleapis.com `
    storage.googleapis.com `
    cloudbuild.googleapis.com `
    --project $PROJECT

# ---------------------------------------------------------------------------
# 2. Criar bucket GCS para armazenar tokens OAuth do Bling
# ---------------------------------------------------------------------------
Write-Host "`n[2/9] Criando bucket GCS para tokens..." -ForegroundColor Cyan
gcloud storage buckets create "gs://$GCS_BUCKET" `
    --project $PROJECT `
    --location $REGION `
    --uniform-bucket-level-access
# (ignora erro se o bucket já existir)

# Fazer upload do tokens.json local para o GCS
Write-Host "      Fazendo upload do tokens.json para gs://$GCS_BUCKET/bling/tokens.json"
gcloud storage cp $TOKENS_LOCAL "gs://$GCS_BUCKET/bling/tokens.json"

# ---------------------------------------------------------------------------
# 3. Criar repositório no Artifact Registry
# ---------------------------------------------------------------------------
Write-Host "`n[3/9] Criando repositório Artifact Registry..." -ForegroundColor Cyan
gcloud artifacts repositories create $REPO `
    --repository-format docker `
    --location $REGION `
    --project $PROJECT
# (ignora erro se já existir)

# ---------------------------------------------------------------------------
# 4. Criar secrets no Secret Manager
# ---------------------------------------------------------------------------
Write-Host "`n[4/9] Criando secrets no Secret Manager..." -ForegroundColor Cyan

# DB_PASSWORD
$dbPass = Read-Host "  DB_PASSWORD (deixe em branco para usar o do .env)"
if ($dbPass -eq "") {
    # Lê do .env local
    $envContent = Get-Content .env | Where-Object { $_ -match "^DB_PASSWORD" }
    $dbPass = ($envContent -split "=", 2)[1].Trim().Trim('"')
}
$dbPass | gcloud secrets create $SECRET_DB_PASS `
    --data-file=- --project $PROJECT
# Se já existir, adiciona nova versão:
# $dbPass | gcloud secrets versions add $SECRET_DB_PASS --data-file=-

# BLING_CLIENT_SECRET
$blingSecret = Read-Host "  BLING_CLIENT_SECRET (deixe em branco para usar o do .env)"
if ($blingSecret -eq "") {
    $envContent = Get-Content .env | Where-Object { $_ -match "^BLING_CLIENT_SECRET" }
    $blingSecret = ($envContent -split "=", 2)[1].Trim().Trim('"')
}
$blingSecret | gcloud secrets create $SECRET_BLING_SEC `
    --data-file=- --project $PROJECT

# service_account.json do Google Sheets
Write-Host "  Criando secret para service_account.json..."
gcloud secrets create $SECRET_SA_JSON `
    --data-file service_account.json `
    --project $PROJECT

# ---------------------------------------------------------------------------
# 5. Build e push da imagem Docker
# ---------------------------------------------------------------------------
Write-Host "`n[5/9] Build e push da imagem Docker..." -ForegroundColor Cyan
gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
docker build -f Dockerfile.pipeline -t $IMAGE .
docker push $IMAGE

# ---------------------------------------------------------------------------
# 6. Criar o Cloud Run Job
# ---------------------------------------------------------------------------
Write-Host "`n[6/9] Criando Cloud Run Job '$JOB_NAME'..." -ForegroundColor Cyan

# Lê variáveis não-secretas do .env
$envContent = Get-Content .env
$blingId   = (($envContent | Where-Object { $_ -match "^BLING_CLIENT_ID" }) -split "=", 2)[1].Trim().Trim('"')
$sheetsId  = (($envContent | Where-Object { $_ -match "^GSHEETS_SPREADSHEET_ID" }) -split "=", 2)[1].Trim().Trim('"')

gcloud run jobs create $JOB_NAME `
    --image $IMAGE `
    --region $REGION `
    --project $PROJECT `
    --task-timeout 3600 `
    --max-retries 1 `
    --set-env-vars "DB_HOST=34.44.240.153,DB_PORT=5432,DB_NAME=postgres,DB_USER=api_user,BLING_CLIENT_ID=$blingId,GSHEETS_SPREADSHEET_ID=$sheetsId,GCS_BUCKET=$GCS_BUCKET,GSHEETS_CREDENTIALS=/secrets/sa.json" `
    --set-secrets "DB_PASSWORD=$SECRET_DB_PASS`:latest,BLING_CLIENT_SECRET=$SECRET_BLING_SEC`:latest" `
    --update-secrets "/secrets/sa.json=$SECRET_SA_JSON`:latest"

# ---------------------------------------------------------------------------
# 7. Criar service account para o Cloud Scheduler
# ---------------------------------------------------------------------------
Write-Host "`n[7/9] Criando service account para o Cloud Scheduler..." -ForegroundColor Cyan
$SA_EMAIL = "$SA_NAME@$PROJECT.iam.gserviceaccount.com"

gcloud iam service-accounts create $SA_NAME `
    --display-name "Bling Pipeline Scheduler" `
    --project $PROJECT

# Permissão para executar o Cloud Run Job
gcloud projects add-iam-policy-binding $PROJECT `
    --member "serviceAccount:$SA_EMAIL" `
    --role "roles/run.invoker"

# ---------------------------------------------------------------------------
# 8. Criar o Cloud Scheduler job
# ---------------------------------------------------------------------------
Write-Host "`n[8/9] Criando Cloud Scheduler job (a cada hora)..." -ForegroundColor Cyan
$JOB_URI = "https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/$JOB_NAME`:run"

gcloud scheduler jobs create http "$JOB_NAME-hourly" `
    --location $REGION `
    --project $PROJECT `
    --schedule $SCHEDULE `
    --uri $JOB_URI `
    --http-method POST `
    --oauth-service-account-email $SA_EMAIL `
    --time-zone "America/Sao_Paulo"

# ---------------------------------------------------------------------------
# 9. Teste: disparo manual imediato
# ---------------------------------------------------------------------------
Write-Host "`n[9/9] Disparando execução de teste..." -ForegroundColor Cyan
gcloud run jobs execute $JOB_NAME `
    --region $REGION `
    --project $PROJECT `
    --wait

Write-Host "`nDeploy concluído!" -ForegroundColor Green
Write-Host "  Job:        https://console.cloud.google.com/run/jobs?project=$PROJECT"
Write-Host "  Scheduler:  https://console.cloud.google.com/cloudscheduler?project=$PROJECT"
Write-Host "  Logs:       gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME' --project $PROJECT --limit 50"
