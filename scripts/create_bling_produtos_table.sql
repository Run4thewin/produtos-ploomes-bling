-- create_bling_produtos_table.sql
--
-- Cria a tabela bling_produtos, espelhando o catalogo de produtos do Bling
-- no Postgres local, no mesmo padrao das demais tabelas bling_* (orders,
-- contacts, nfe, contas_pagar, contas_receber, naturezas_operacao).
--
-- Requer privilegio de owner do schema (api_user nao tem CREATE TABLE).
-- Rode com uma credencial admin/postgres:
--   psql "host=<host> port=5432 dbname=<db> user=postgres" \
--        -f scripts/create_bling_produtos_table.sql
--
-- Idempotente: pode ser rodado mais de uma vez sem erro (IF NOT EXISTS).

BEGIN;

CREATE TABLE IF NOT EXISTS bling_produtos (
    id                bigint PRIMARY KEY,
    codigo            text,
    nome              text,
    descricao_curta   text,
    preco             numeric,
    situacao          text,
    tipo              text,
    formato           text,
    marca             text,
    ncm               text,
    peso_liquido      numeric,
    peso_bruto        numeric,
    largura           numeric,
    altura            numeric,
    profundidade      numeric,
    created_at        timestamp without time zone,
    updated_at        timestamp without time zone,
    raw_json          jsonb
);

CREATE INDEX IF NOT EXISTS idx_bling_produtos_codigo ON bling_produtos (codigo);
CREATE INDEX IF NOT EXISTS idx_bling_produtos_nome    ON bling_produtos (lower(nome));

-- Permite que o api_user (usado pela aplicacao/fetcher) grave nessa tabela.
GRANT SELECT, INSERT, UPDATE ON bling_produtos TO api_user;

COMMIT;

-- Verificacao pos-migracao:
-- SELECT count(*), count(*) FILTER (WHERE codigo IS NOT NULL AND codigo <> '') AS com_codigo
-- FROM bling_produtos;
