# Backend — Aplicativo de Manutenção Industrial

API FastAPI (SQLAlchemy 2.x async + PostgreSQL 16 + Alembic) multi-tenant por `empresa_id`,
com arquitetura estrita em 4 camadas (Router → Service → Repository → Model). As regras de
projeto estão em [`CLAUDE.md`](./CLAUDE.md).

> **Status:** Passo 1 da roadmap — `empresa`, `perfil`, `permissao`, `usuario` + autenticação
> (login, refresh, recuperação de senha) com testes. Próximos passos (equipamentos, estoque,
> manutenções, dashboard, V2/IA) descritos no `CLAUDE.md`.

## Estrutura

```
app/
  core/        config (pydantic-settings) + security (JWT/bcrypt)
  db/          base (engine async, mixins) + session (get_db)
  models/      ORM (empresa, perfil, permissao, usuario)
  schemas/     Pydantic Create/Update/Read + auth
  repositories/ acesso a dados (único lugar que toca a AsyncSession)
  services/    regra de negócio + transações
  api/v1/      routers (auth, empresas, perfis, usuarios) + deps (auth/permissão)
alembic/       migrações (0001: extensões + tabelas do Passo 1)
scripts/seed.py  perfis padrão + admin de bootstrap
tests/         pytest (auth, usuarios) — roda em SQLite, sem Postgres
deploy/        Terraform + guia de deploy no Cloud Run + Cloud SQL
```

## Desenvolvimento local

Requer Python 3.12+ e (para rodar de verdade) PostgreSQL 16. Os testes rodam sem Postgres.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env               # ajuste DATABASE_URL

# Migrações + seed
alembic upgrade head
python -m scripts.seed             # cria perfis + admin@demo.local / admin123

# API
uvicorn app.main:app --reload --port 8080
```

- Health: http://127.0.0.1:8080/health
- Swagger: http://127.0.0.1:8080/docs

### Fluxo rápido

```bash
# login
curl -X POST localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@demo.local","senha":"admin123"}'

# usar o access_token retornado:
curl localhost:8080/api/v1/usuarios -H "Authorization: Bearer <ACCESS_TOKEN>"
```

## Testes

```bash
pytest
```

Cobrem: login (ok/inválido), refresh, `/me`, criação de usuário (happy path),
erro de permissão (403) e isolamento multi-tenant na listagem.

## Deploy (Google Cloud Run + Cloud SQL)

Terraform completo + passo a passo em [`deploy/README.md`](./deploy/README.md).

## Convenções (resumo do CLAUDE.md)

- Acesso a dados **só** via ORM (sem SQL cru); joins com `.join()`/`selectinload`.
- Router não monta query nem toca `AsyncSession`; Service orquestra transação; Repository
  é o único que executa `session.execute`/`add`.
- Toda listagem filtra por `empresa_id` do usuário logado (nunca vindo do client).
- Soft delete (`ativo=false`) em vez de DELETE físico.
