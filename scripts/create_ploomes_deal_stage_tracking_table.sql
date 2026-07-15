-- create_ploomes_deal_stage_tracking_table.sql
--
-- Cria a tabela ploomes_deal_stage_tracking, guardando o ultimo estagio de
-- Deal que a propria aplicacao observou (o campo LastStageId do Ploomes nao
-- serve para isso -- testado contra a conta real, sempre igual ao StageId
-- atual). Usado para detectar transicoes reais de estagio (ex: Deal pulando
-- direto de "Analise de Credito" para "Logistica", sem passar por
-- "Gerar pedido de venda") em app/services/sync_deal_to_bling_order.py.
--
-- Requer privilegio de owner do schema (api_user nao tem CREATE TABLE).
-- Rode com uma credencial admin/postgres:
--   psql "host=<host> port=5432 dbname=<db> user=postgres" \
--        -f scripts/create_ploomes_deal_stage_tracking_table.sql
--
-- Idempotente: pode ser rodado mais de uma vez sem erro (IF NOT EXISTS).

BEGIN;

CREATE TABLE IF NOT EXISTS ploomes_deal_stage_tracking (
    ploomes_deal_id     bigint PRIMARY KEY,
    last_seen_stage_id  bigint NOT NULL,
    updated_at          timestamp without time zone DEFAULT now()
);

-- Permite que o api_user (usado pela aplicacao) grave nessa tabela.
GRANT SELECT, INSERT, UPDATE ON ploomes_deal_stage_tracking TO api_user;

COMMIT;

-- Verificacao pos-migracao:
-- SELECT count(*) FROM ploomes_deal_stage_tracking;
