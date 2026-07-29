#!/bin/bash
# Script para criar Cloud Scheduler job para renovação automática de token Bling
# Uso: bash setup-cloud-scheduler.sh <PROJECT_ID> <SERVICE_URL> <INTERNAL_SECRET>

set -e

if [ $# -ne 3 ]; then
    echo "Uso: bash setup-cloud-scheduler.sh <PROJECT_ID> <SERVICE_URL> <INTERNAL_SECRET>"
    echo ""
    echo "Exemplo:"
    echo "  bash setup-cloud-scheduler.sh my-gcp-project https://produtos-ploomes-bling-abc123.run.app my-secret-key"
    exit 1
fi

PROJECT_ID=$1
SERVICE_URL=$2
INTERNAL_SECRET=$3

echo "🔧 Criando Cloud Scheduler job..."
echo "  Project: $PROJECT_ID"
echo "  Service URL: $SERVICE_URL"
echo "  Schedule: 3 AM diariamente (timezone America/Sao_Paulo)"
echo ""

# Substituir variáveis no template
sed -e "s|\${PROJECT_ID}|$PROJECT_ID|g" \
    -e "s|\${SERVICE_URL}|$SERVICE_URL|g" \
    -e "s|\${INTERNAL_SECRET}|$INTERNAL_SECRET|g" \
    cloud-scheduler.yaml > /tmp/cloud-scheduler-filled.yaml

# Criar o job
gcloud scheduler jobs create app-engine bling-token-refresh \
    --location us-central1 \
    --schedule "0 3 * * *" \
    --timezone "America/Sao_Paulo" \
    --http-method POST \
    --uri "$SERVICE_URL/jobs/refresh-bling-token" \
    --oidc-service-account-email "cloud-scheduler@$PROJECT_ID.iam.gserviceaccount.com" \
    --headers "x-internal-secret=$INTERNAL_SECRET" \
    --project $PROJECT_ID 2>/dev/null || {
        echo "❌ Job já existe. Atualizando..."
        gcloud scheduler jobs update app-engine bling-token-refresh \
            --location us-central1 \
            --schedule "0 3 * * *" \
            --timezone "America/Sao_Paulo" \
            --http-method POST \
            --uri "$SERVICE_URL/jobs/refresh-bling-token" \
            --oidc-service-account-email "cloud-scheduler@$PROJECT_ID.iam.gserviceaccount.com" \
            --headers "x-internal-secret=$INTERNAL_SECRET" \
            --project $PROJECT_ID
    }

echo "✅ Cloud Scheduler job criado/atualizado com sucesso!"
echo ""
echo "Verificar status:"
echo "  gcloud scheduler jobs list --location us-central1 --project $PROJECT_ID"
echo ""
echo "Testar manualmente:"
echo "  gcloud scheduler jobs run bling-token-refresh --location us-central1 --project $PROJECT_ID"
echo ""
echo "Ver logs:"
echo "  gcloud scheduler jobs describe bling-token-refresh --location us-central1 --project $PROJECT_ID"

rm -f /tmp/cloud-scheduler-filled.yaml
