-- create_bling_order_links_table.sql
--
-- Cria a tabela bling_order_links, guardando o vinculo entre um Deal do
-- Ploomes e o pedido de venda / pedido de compra gerados no Bling a partir
-- dele. Usado pelo trigger de "Logistica" (app/services/sync_deal_to_bling_order.py)
-- para achar rapidamente o pedido de venda de um Deal sem precisar re-parsear
-- o texto salvo no card do Ploomes.
--
-- Requer privilegio de owner do schema (api_user nao tem CREATE TABLE).
-- Rode com uma credencial admin/postgres:
--   psql "host=<host> port=5432 dbname=<db> user=postgres" \
--        -f scripts/create_bling_order_links_table.sql
--
-- Idempotente: pode ser rodado mais de uma vez sem erro (IF NOT EXISTS).

BEGIN;

CREATE TABLE IF NOT EXISTS bling_order_links (
    ploomes_deal_id         bigint PRIMARY KEY,
    bling_pedido_venda_id   bigint,
    bling_pedido_compra_id  bigint,
    last_situacao_id        integer,
    updated_at              timestamp without time zone DEFAULT now()
);

-- Permite que o api_user (usado pela aplicacao) grave nessa tabela.
GRANT SELECT, INSERT, UPDATE ON bling_order_links TO api_user;

COMMIT;

-- Verificacao pos-migracao:
-- SELECT count(*) FROM bling_order_links;
