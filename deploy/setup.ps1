# Setup inicial no Google Cloud para ploomes-bling-sync
# Uso: .\deploy\setup.ps1 -ProjectId "meu-projeto" -Region "us-central1"

param(
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [string]$Region = "us-central1",
    [string]$Repository = "ploomes-bling",
    [string]$QueueName = "ploomes-bling-products",
    [string]$BucketName = ""
)

if (-not $BucketName) {
    $BucketName = "$ProjectId-ploomes-bling-tokens"
}

$TasksSa = "ploomes-bling-tasks@$ProjectId.iam.gserviceaccount.com"
$RunSa = "ploomes-bling-run@$ProjectId.iam.gserviceaccount.com"

Write-Host "Projeto: $ProjectId | Regiao: $Region"

gcloud config set project $ProjectId

gcloud services enable `
    run.googleapis.com `
    cloudtasks.googleapis.com `
    cloudscheduler.googleapis.com `
    artifactregistry.googleapis.com `
    secretmanager.googleapis.com `
    cloudbuild.googleapis.com `
    storage.googleapis.com

gcloud artifacts repositories create $Repository `
    --repository-format=docker `
    --location=$Region `
    --description="Imagens ploomes-bling-sync" `
    2>$null

gsutil mb -l $Region "gs://$BucketName" 2>$null

gcloud iam service-accounts create ploomes-bling-tasks --display-name="Cloud Tasks ploomes-bling" 2>$null
gcloud iam service-accounts create ploomes-bling-run --display-name="Cloud Run ploomes-bling" 2>$null

gcloud tasks queues create $QueueName --location=$Region 2>$null

# Permissoes: Tasks invoca Cloud Run; Run le/escreve tokens no GCS
gcloud run services add-iam-policy-binding ploomes-bling-sync `
    --region=$Region `
    --member="serviceAccount:$TasksSa" `
    --role="roles/run.invoker" `
    2>$null

gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$RunSa" `
    --role="roles/storage.objectAdmin" `
    --condition=None

Write-Host ""
Write-Host "Proximos passos manuais:"
Write-Host "1. Criar secrets: bling-client-id, bling-client-secret, ploomes-user-key, internal-secret"
Write-Host "2. Copiar tokens.json do OAuth Bling para gs://$BucketName/bling/tokens.json"
Write-Host "3. Descobrir PLOOMES_GROUP_ID e configurar no deploy"
Write-Host "4. Deploy: gcloud builds submit --config cloudbuild.yaml"
Write-Host "5. Configurar webhook Bling -> https://SEU-SERVICO/webhooks/bling"
Write-Host "6. Criar Cloud Scheduler para POST /jobs/reconcile (diario)"
