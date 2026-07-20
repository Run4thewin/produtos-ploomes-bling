-- 003_bling_new_entities.sql
-- GERADO por scripts/generate_ddl_from_specs.py a partir de
-- blng_fetcher/specs/expansion.py — nao editar a mao; re-gerar.
--
-- Requer privilegio de owner do schema (api_user nao tem CREATE TABLE).
-- Rode com uma credencial admin/postgres:
--   psql "host=<host> port=5432 dbname=<db> user=postgres" \
--        -f scripts/sql/003_bling_new_entities.sql
--
-- Idempotente (IF NOT EXISTS).

BEGIN;

-- pedidos_compras (pedidos/compras)
CREATE TABLE IF NOT EXISTS bling_pedidos_compras (
    id                bigint PRIMARY KEY,
    numero                     bigint,
    data                       date,
    data_prevista              date,
    total_produtos             numeric,
    total                      numeric,
    fornecedor_id              bigint,
    situacao_id                bigint,
    situacao_valor             bigint,
    ordem_compra               text,
    observacoes                text,
    observacoes_internas       text,
    desconto_valor             numeric,
    desconto_unidade           text,
    categoria_id               bigint,
    tributacao_total_icms      numeric,
    tributacao_total_ipi       numeric,
    transporte_frete           numeric,
    transporte_transportador   text,
    transporte_frete_por_conta bigint,
    transporte_peso_bruto      numeric,
    transporte_volumes         bigint,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_pedidos_compras TO api_user;

-- propostas (propostas-comerciais)
CREATE TABLE IF NOT EXISTS bling_propostas_comerciais (
    id                bigint PRIMARY KEY,
    numero                     bigint,
    data                       date,
    situacao                   text,
    total                      numeric,
    total_produtos             numeric,
    total_outros_itens         numeric,
    contato_id                 bigint,
    loja_id                    bigint,
    vendedor_id                bigint,
    desconto                   numeric,
    outras_despesas            numeric,
    garantia                   bigint,
    data_proximo_contato       date,
    aos_cuidados_de            text,
    introducao                 text,
    prazo_entrega              text,
    observacoes                text,
    observacao_interna         text,
    transporte_frete_modalidade bigint,
    transporte_frete           numeric,
    transporte_quantidade_volumes bigint,
    transporte_prazo_entrega   bigint,
    transporte_peso_bruto      numeric,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_propostas_comerciais TO api_user;

-- nfce (nfce)
CREATE TABLE IF NOT EXISTS bling_nfce (
    id                bigint PRIMARY KEY,
    numero                     text,
    serie                      text,
    situation                  text,
    contact_id                 bigint,
    contact_name               text,
    total                      numeric,
    issue_date                 date,
    chave_acesso               text,
    tipo                       bigint,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_nfce TO api_user;

-- estoques_saldos (estoques/saldos)
CREATE TABLE IF NOT EXISTS bling_estoques_saldos (
    id                bigint PRIMARY KEY,
    produto_codigo             text,
    saldo_fisico_total         numeric,
    saldo_virtual_total        numeric,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_estoques_saldos TO api_user;

-- depositos (depositos)
CREATE TABLE IF NOT EXISTS bling_depositos (
    id                bigint PRIMARY KEY,
    descricao                  text,
    situacao                   bigint,
    padrao                     boolean,
    desconsiderar_saldo        boolean,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_depositos TO api_user;

-- vendedores (vendedores)
CREATE TABLE IF NOT EXISTS bling_vendedores (
    id                bigint PRIMARY KEY,
    desconto_limite            numeric,
    loja_id                    bigint,
    contato_id                 bigint,
    contato_nome               text,
    contato_situacao           text,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_vendedores TO api_user;

-- categorias_produtos (categorias/produtos)
CREATE TABLE IF NOT EXISTS bling_categorias_produtos (
    id                bigint PRIMARY KEY,
    descricao                  text,
    categoria_pai_id           bigint,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_categorias_produtos TO api_user;

-- categorias_receitas_despesas (categorias/receitas-despesas)
CREATE TABLE IF NOT EXISTS bling_categorias_receitas_despesas (
    id                bigint PRIMARY KEY,
    descricao                  text,
    id_categoria_pai           bigint,
    tipo                       bigint,
    id_grupo_dre               bigint,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_categorias_receitas_despesas TO api_user;

-- grupos_produtos (grupos-produtos)
CREATE TABLE IF NOT EXISTS bling_grupos_produtos (
    id                bigint PRIMARY KEY,
    nome                       text,
    grupo_produto_pai_id       bigint,
    grupo_produto_pai_nome     text,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_grupos_produtos TO api_user;

-- contatos_tipos (contatos/tipos)
CREATE TABLE IF NOT EXISTS bling_contatos_tipos (
    id                bigint PRIMARY KEY,
    descricao                  text,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_contatos_tipos TO api_user;

-- formas_pagamentos (formas-pagamentos)
CREATE TABLE IF NOT EXISTS bling_formas_pagamentos (
    id                bigint PRIMARY KEY,
    descricao                  text,
    tipo_pagamento             bigint,
    situacao                   bigint,
    fixa                       boolean,
    padrao                     bigint,
    finalidade                 bigint,
    juros                      numeric,
    multa                      numeric,
    condicao                   text,
    destino                    bigint,
    utiliza_dias_uteis         boolean,
    taxas_aliquota             numeric,
    taxas_valor                numeric,
    taxas_prazo                bigint,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_formas_pagamentos TO api_user;

-- contas_contabeis (contas-contabeis)
CREATE TABLE IF NOT EXISTS bling_contas_contabeis (
    id                bigint PRIMARY KEY,
    descricao                  text,
    saldo_inicial              numeric,
    data_inicio_transacoes     text,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_contas_contabeis TO api_user;

-- canais_venda (canais-venda)
CREATE TABLE IF NOT EXISTS bling_canais_venda (
    id                bigint PRIMARY KEY,
    descricao                  text,
    tipo                       text,
    situacao                   bigint,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_canais_venda TO api_user;

-- campos_customizados_modulos (campos-customizados/modulos)
CREATE TABLE IF NOT EXISTS bling_campos_customizados_modulos (
    id                bigint PRIMARY KEY,
    nome                       text,
    modulo                     text,
    agrupador                  text,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_campos_customizados_modulos TO api_user;

-- empresas (empresas/me/dados-basicos)
CREATE TABLE IF NOT EXISTS bling_empresas (
    id                bigint PRIMARY KEY,
    nome                       text,
    cnpj                       text,
    email                      text,
    data_contrato              date,
    created_at        timestamp without time zone NOT NULL DEFAULT now(),
    updated_at        timestamp without time zone NOT NULL DEFAULT now(),
    raw_json          jsonb,
    source_hash       text,
    deleted_at        timestamptz
);
GRANT SELECT, INSERT, UPDATE ON bling_empresas TO api_user;

-- Sem escopo OAuth nesta conta (tabela criada quando habilitar):
--   nfse -> bling_nfse (nfse)
--   contratos -> bling_contratos (contratos)
--   logisticas -> bling_logisticas (logisticas)
--   situacoes_modulos -> bling_situacoes_modulos (situacoes/modulos)

COMMIT;
