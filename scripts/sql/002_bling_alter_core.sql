-- 002_bling_alter_core.sql
--
-- Adiciona colunas de infraestrutura do novo engine as 7 tabelas ja existentes:
--   source_hash : md5 do item de listagem canonico (gatilho barato de "mudou?")
--   deleted_at  : registro sumiu da API (marcado apenas em full sweep completo)
--
-- Nenhuma coluna existente e' alterada ou removida; views e sync_to_sheets
-- continuam funcionando.
--
-- Requer privilegio de owner do schema (api_user nao tem ALTER TABLE).
-- Rode com uma credencial admin/postgres:
--   psql "host=<host> port=5432 dbname=<db> user=postgres" \
--        -f scripts/sql/002_bling_alter_core.sql
--
-- Idempotente (IF NOT EXISTS).

BEGIN;

ALTER TABLE bling_orders
    ADD COLUMN IF NOT EXISTS source_hash text,
    ADD COLUMN IF NOT EXISTS deleted_at  timestamptz;

ALTER TABLE bling_contacts
    ADD COLUMN IF NOT EXISTS source_hash text,
    ADD COLUMN IF NOT EXISTS deleted_at  timestamptz;

ALTER TABLE bling_nfe
    ADD COLUMN IF NOT EXISTS source_hash text,
    ADD COLUMN IF NOT EXISTS deleted_at  timestamptz;

ALTER TABLE bling_contas_pagar
    ADD COLUMN IF NOT EXISTS source_hash text,
    ADD COLUMN IF NOT EXISTS deleted_at  timestamptz;

ALTER TABLE bling_contas_receber
    ADD COLUMN IF NOT EXISTS source_hash text,
    ADD COLUMN IF NOT EXISTS deleted_at  timestamptz;

ALTER TABLE bling_naturezas_operacao
    ADD COLUMN IF NOT EXISTS source_hash text,
    ADD COLUMN IF NOT EXISTS deleted_at  timestamptz;

ALTER TABLE bling_produtos
    ADD COLUMN IF NOT EXISTS source_hash text,
    ADD COLUMN IF NOT EXISTS deleted_at  timestamptz;

COMMIT;

-- Verificacao pos-migracao:
-- SELECT table_name, column_name FROM information_schema.columns
-- WHERE column_name IN ('source_hash', 'deleted_at')
--   AND table_name LIKE 'bling\_%' ORDER BY table_name;
