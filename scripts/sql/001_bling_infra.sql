-- 001_bling_infra.sql
--
-- Infraestrutura do fetcher expandido:
--   bling_change_history : historico de mudancas campo a campo (auditoria)
--   bling_sync_state     : watermark incremental + retomada por entidade
--
-- Requer privilegio de owner do schema (api_user nao tem CREATE TABLE).
-- Rode com uma credencial admin/postgres:
--   psql "host=<host> port=5432 dbname=<db> user=postgres" \
--        -f scripts/sql/001_bling_infra.sql
--
-- Idempotente: pode ser rodado mais de uma vez sem erro (IF NOT EXISTS).

BEGIN;

CREATE TABLE IF NOT EXISTS bling_change_history (
    id          bigserial   PRIMARY KEY,
    run_id      uuid        NOT NULL,          -- agrupa mudancas da mesma execucao
    entity      text        NOT NULL,          -- nome da spec: 'contacts', 'orders'...
    entity_id   text        NOT NULL,          -- text p/ suportar PK composta ("prod:dep")
    op          char(1)     NOT NULL CHECK (op IN ('I','U','D','R')),
    field       text,                          -- NULL para I/D/R
    old_value   text,
    new_value   text,
    changed_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bch_entity_record
    ON bling_change_history (entity, entity_id, changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_bch_changed_at
    ON bling_change_history (changed_at);
CREATE INDEX IF NOT EXISTS idx_bch_field
    ON bling_change_history (entity, field) WHERE op = 'U';

CREATE TABLE IF NOT EXISTS bling_sync_state (
    entity             text PRIMARY KEY,
    watermark          timestamptz,   -- inicio da ultima varredura COMPLETA (menos overlap)
    last_run_at        timestamptz,
    last_run_id        uuid,
    last_status        text,          -- 'ok' | 'quota' | 'error' | 'partial'
    last_page          integer,       -- p/ retomar carga interrompida por quota
    last_full_sweep_at timestamptz,   -- ultima varredura sem filtro incremental
    details            jsonb          -- contadores, params usados, erros
);

GRANT SELECT, INSERT, UPDATE ON bling_change_history TO api_user;
GRANT SELECT, INSERT, UPDATE ON bling_sync_state     TO api_user;
GRANT USAGE ON SEQUENCE bling_change_history_id_seq  TO api_user;

COMMIT;

-- Verificacao pos-migracao:
-- SELECT entity, count(*) FILTER (WHERE op='U') AS updates, max(changed_at)
-- FROM bling_change_history GROUP BY entity;
-- SELECT * FROM bling_sync_state ORDER BY last_run_at DESC;
