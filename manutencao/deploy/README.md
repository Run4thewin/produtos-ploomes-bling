# Deploy — Cloud Run + Cloud SQL (Terraform)

Infraestrutura provisionada por Terraform (`deploy/terraform/`):

- **Artifact Registry** (repo Docker `manutencao`)
- **Cloud SQL PostgreSQL 16** (instância + banco + usuário; senha gerada)
- **Secret Manager** (`db-password`, `jwt-secret`)
- **Service Account** do Cloud Run com `cloudsql.client` + `secretmanager.secretAccessor`
- **Cloud Run v2** conectado ao Cloud SQL por socket unix (`/cloudsql/<connection_name>`)

As migrações Alembic rodam automaticamente no start do container (`entrypoint.sh`), e o
seed (perfis + admin) roda quando `seed_on_start = true`.

## Pré-requisitos

- `gcloud` autenticado (`gcloud auth login` + `gcloud config set project SEU_PROJETO`)
- `terraform >= 1.5`
- Projeto GCP com billing habilitado

## Passo a passo

```bash
cd deploy/terraform
cp terraform.tfvars.example terraform.tfvars   # edite project_id/region
terraform init
```

### 1) Criar APIs + repositório de imagens

```bash
terraform apply \
  -target=google_project_service.enabled \
  -target=google_artifact_registry_repository.docker
```

### 2) Build e push da imagem

Autentique o Docker no Artifact Registry e faça o build (na raiz do projeto):

```bash
cd ../..                      # volta para manutencao/
gcloud auth configure-docker us-central1-docker.pkg.dev

# via Cloud Build (recomendado)
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_REGION=us-central1,_REPO=manutencao,_TAG=latest

# — ou — build local
# docker build -t us-central1-docker.pkg.dev/SEU_PROJETO/manutencao/api:latest .
# docker push us-central1-docker.pkg.dev/SEU_PROJETO/manutencao/api:latest
```

### 3) Provisionar tudo (Cloud SQL, secrets, Cloud Run)

Garanta que `image` em `terraform.tfvars` aponta para a imagem publicada, então:

```bash
cd deploy/terraform
terraform apply
```

Saídas úteis:

```bash
terraform output service_url               # URL da API
terraform output instance_connection_name  # PROJECT:REGION:INSTANCE
terraform output -raw db_password          # senha do banco (sensível)
```

### 4) Verificar

```bash
curl "$(terraform output -raw service_url)/health"      # {"status":"ok"}
# Swagger: <service_url>/docs
```

Login inicial (usuário admin criado pelo seed — troque a senha depois):

```bash
curl -X POST "$(terraform output -raw service_url)/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@demo.local","senha":"admin123"}'
```

> Ajuste o admin inicial via env `SEED_ADMIN_EMAIL` / `SEED_ADMIN_SENHA` / `SEED_EMPRESA_CNPJ`
> na Service Account/Cloud Run, ou desligue com `seed_on_start = false` após o primeiro deploy.

## Atualizações (novo deploy da app)

```bash
# rebuild + push (passo 2) com nova _TAG, então:
terraform apply -var="image=us-central1-docker.pkg.dev/SEU_PROJETO/manutencao/api:NOVA_TAG"
```

## Destruir

```bash
terraform destroy
```

> `db_deletion_protection = false` por padrão para facilitar teardown. Em produção,
> defina `true` e habilite backups/HA.

## Notas de produção

- As migrações rodam no start; com múltiplas instâncias, considere um **Cloud Run Job**
  dedicado para migração (evita corrida) e mantenha `min_instances` adequado.
- Restrinja `allow_unauthenticated = false` e coloque atrás de um API Gateway / IAP se
  o acesso não for público.
- Cloud SQL com IP público + conector é seguro (autenticação IAM); para isolamento total,
  migre para IP privado + VPC.
