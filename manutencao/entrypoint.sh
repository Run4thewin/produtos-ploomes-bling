#!/bin/sh
# Aplica as migrações e sobe a API. As migrações usam a URL síncrona (psycopg)
# derivada das mesmas variáveis (DB_USER/DB_PASSWORD/DB_NAME/INSTANCE_CONNECTION_NAME).
set -e

echo "==> Aplicando migrações Alembic..."
alembic upgrade head

if [ "${SEED_ON_START:-false}" = "true" ]; then
  echo "==> Executando seed inicial..."
  python -m scripts.seed
fi

echo "==> Iniciando API na porta ${PORT:-8080}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
