-- 004_bling_views.sql
--
-- Views de auditoria do historico de mudancas do fetcher.
-- Rode como postgres (mesmo padrao dos demais scripts/sql):
--   psql "host=<host> port=5432 dbname=<db> user=postgres" \
--        -f scripts/sql/004_bling_views.sql

BEGIN;

-- Historico legivel, com o rotulo da operacao decodificado.
CREATE OR REPLACE VIEW vw_bling_auditoria AS
SELECT
    h.changed_at,
    h.entity,
    h.entity_id,
    CASE h.op
        WHEN 'I' THEN 'criado'
        WHEN 'U' THEN 'alterado'
        WHEN 'D' THEN 'removido'
        WHEN 'R' THEN 'reapareceu'
    END                     AS operacao,
    h.field                 AS campo,
    h.old_value             AS valor_anterior,
    h.new_value             AS valor_novo,
    h.run_id
FROM bling_change_history h;

-- Resumo por entidade: volume de mudancas e ultima atividade.
CREATE OR REPLACE VIEW vw_bling_auditoria_resumo AS
SELECT
    h.entity,
    count(*) FILTER (WHERE h.op = 'I')                    AS criados,
    count(*) FILTER (WHERE h.op = 'U')                    AS campos_alterados,
    count(DISTINCT h.entity_id) FILTER (WHERE h.op = 'U') AS registros_alterados,
    count(*) FILTER (WHERE h.op = 'D')                    AS removidos,
    max(h.changed_at)                                     AS ultima_mudanca
FROM bling_change_history h
GROUP BY h.entity;

GRANT SELECT ON vw_bling_auditoria, vw_bling_auditoria_resumo TO api_user;

COMMIT;

-- Exemplos de consulta:
-- SELECT * FROM vw_bling_auditoria WHERE entity = 'contacts'
--   AND campo IN ('credit_limit', 'document') ORDER BY changed_at DESC LIMIT 50;
-- SELECT * FROM vw_bling_auditoria_resumo ORDER BY ultima_mudanca DESC;
