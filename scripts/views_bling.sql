-- =============================================================================
-- views_bling.sql
-- Views analíticas cruzando as 5 tabelas do Bling.
--
-- REQUER: usuário com CREATE ON SCHEMA public (ex: postgres / cloudsqlsuperuser)
--
-- Opção 1 — psql local com túnel ou IP liberado:
--   psql -h 34.44.240.153 -U postgres -d postgres -f scripts/views_bling.sql
--
-- Opção 2 — Cloud SQL Studio (GCP Console):
--   Abrir: console.cloud.google.com -> SQL -> Instância -> Cloud SQL Studio
--   Conectar como postgres/admin e colar o conteúdo deste arquivo.
--
-- Após criar as views, libere acesso ao api_user (incluído no final do arquivo).
--
-- Views geradas:
--   vw_bling_contato_resumo  -- 1 linha por contato com totais de cada entidade
--   vw_bling_movimentos      -- UNION de todos os movimentos financeiros
-- =============================================================================

-- ---------------------------------------------------------------------------
-- View 1: Resumo por contato
-- Uma linha por contato com agregações de pedidos, NF-e, contas a pagar e
-- contas a receber. Usa CTEs para evitar produto cartesiano nos JOINs.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW vw_bling_contato_resumo AS
WITH pedidos AS (
    SELECT
        client_id::bigint                                               AS contact_id,
        COUNT(*)                                                        AS qtd_pedidos,
        SUM(total)                                                      AS total_pedidos,
        SUM(total) FILTER (WHERE status IN ('6','15'))                  AS total_pedidos_aberto,
        SUM(total) FILTER (WHERE status = '9')                         AS total_pedidos_atendido,
        MAX(created_at)                                                 AS ultimo_pedido
    FROM bling_orders
    WHERE client_id ~ '^\d+$'
    GROUP BY client_id
),
nfe AS (
    SELECT
        contact_id,
        COUNT(*)                                                        AS qtd_nfe,
        SUM(total)                                                      AS total_nfe,
        SUM(total) FILTER (WHERE situation = '6')                       AS total_nfe_autorizada,
        MAX(issue_date)                                                 AS ultima_nfe
    FROM bling_nfe
    GROUP BY contact_id
),
receber AS (
    SELECT
        contact_id,
        COUNT(*)                                                        AS qtd_receber,
        SUM(value)                                                      AS total_receber,
        SUM(value) FILTER (WHERE status = '1')                         AS total_receber_aberto,
        SUM(value) FILTER (WHERE status = '5')                         AS total_receber_parcial,
        SUM(value) FILTER (WHERE status = '2')                         AS total_receber_recebido,
        MAX(due_date)                                                   AS ultimo_vencimento_receber
    FROM bling_contas_receber
    GROUP BY contact_id
),
pagar AS (
    SELECT
        supplier_id                                                     AS contact_id,
        COUNT(*)                                                        AS qtd_pagar,
        SUM(value)                                                      AS total_pagar,
        SUM(value) FILTER (WHERE status = '1')                         AS total_pagar_aberto,
        SUM(value) FILTER (WHERE status = '5')                         AS total_pagar_parcial,
        SUM(value) FILTER (WHERE status = '2')                         AS total_pagar_pago,
        MAX(due_date)                                                   AS ultimo_vencimento_pagar
    FROM bling_contas_pagar
    GROUP BY supplier_id
)
SELECT
    -- Identificação do contato
    c.id                                                                AS contact_id,
    c.name                                                              AS nome,
    c.document                                                          AS documento,
    c.person_type                                                       AS tipo_pessoa,
    c.is_supplier                                                       AS fornecedor,
    c.is_client                                                         AS cliente,
    c.email,
    c.phone                                                             AS telefone,
    c.city                                                              AS cidade,
    c.state                                                             AS uf,

    -- Pedidos de venda
    COALESCE(p.qtd_pedidos, 0)                                         AS qtd_pedidos,
    COALESCE(p.total_pedidos, 0)                                       AS total_pedidos,
    COALESCE(p.total_pedidos_aberto, 0)                                AS total_pedidos_aberto,
    COALESCE(p.total_pedidos_atendido, 0)                              AS total_pedidos_atendido,
    p.ultimo_pedido,

    -- NF-e
    COALESCE(n.qtd_nfe, 0)                                             AS qtd_nfe,
    COALESCE(n.total_nfe, 0)                                           AS total_nfe,
    COALESCE(n.total_nfe_autorizada, 0)                                AS total_nfe_autorizada,
    n.ultima_nfe,

    -- Contas a receber
    COALESCE(r.qtd_receber, 0)                                         AS qtd_receber,
    COALESCE(r.total_receber, 0)                                       AS total_receber,
    COALESCE(r.total_receber_aberto, 0)                                AS total_receber_aberto,
    COALESCE(r.total_receber_parcial, 0)                               AS total_receber_parcial,
    COALESCE(r.total_receber_recebido, 0)                              AS total_receber_recebido,
    r.ultimo_vencimento_receber,

    -- Contas a pagar
    COALESCE(pg.qtd_pagar, 0)                                          AS qtd_pagar,
    COALESCE(pg.total_pagar, 0)                                        AS total_pagar,
    COALESCE(pg.total_pagar_aberto, 0)                                 AS total_pagar_aberto,
    COALESCE(pg.total_pagar_parcial, 0)                                AS total_pagar_parcial,
    COALESCE(pg.total_pagar_pago, 0)                                   AS total_pagar_pago,
    pg.ultimo_vencimento_pagar,

    -- Saldo líquido (receber - pagar)
    COALESCE(r.total_receber, 0) - COALESCE(pg.total_pagar, 0)        AS saldo_liquido

FROM bling_contacts c
LEFT JOIN pedidos  p  ON p.contact_id  = c.id
LEFT JOIN nfe      n  ON n.contact_id  = c.id
LEFT JOIN receber  r  ON r.contact_id  = c.id
LEFT JOIN pagar    pg ON pg.contact_id = c.id;


-- ---------------------------------------------------------------------------
-- View 2: Movimentos financeiros unificados — todos os campos
-- UNION ALL de pedidos, NF-e, contas receber e contas pagar.
-- Campos exclusivos de cada entidade ficam NULL nas demais.
-- Contas a pagar têm valor negativo (saída de caixa); valor_original sempre positivo.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW vw_bling_movimentos AS

-- ── Pedidos de venda ────────────────────────────────────────────────────────
SELECT
    'Pedido'                                        AS tipo,
    o.id,

    -- status
    CASE o.status
        WHEN '6'  THEN 'Em Aberto'
        WHEN '9'  THEN 'Atendido'
        WHEN '12' THEN 'Cancelado'
        WHEN '15' THEN 'Em Andamento'
        WHEN '21' THEN 'Verificado'
        ELSE o.status
    END                                             AS status,
    o.status                                        AS status_raw,

    -- valores
    o.total                                         AS valor,
    o.total                                         AS valor_original,

    -- datas
    o.created_at::date                              AS data_ref,
    NULL::date                                      AS due_date,
    o.created_at                                    AS data_criacao,
    o.updated_at                                    AS data_atualizacao,

    -- campos de pedido
    o.order_number,
    o.shipping_address,
    o.billing_address,

    -- campos de NF-e
    NULL::text                                      AS nfe_numero,
    NULL::text                                      AS nfe_serie,

    -- campos de contas
    NULL::text                                      AS description,
    NULL::text                                      AS competency,
    NULL::text                                      AS category,

    -- contato (JOIN com bling_contacts + fallback dos campos da ordem)
    o.client_id::bigint                             AS contact_id,
    COALESCE(c.name,     o.client_name)             AS contact_nome,
    COALESCE(c.document, o.client_cpf_cnpj)        AS contact_documento,
    c.person_type                                   AS contact_tipo_pessoa,
    c.is_supplier                                   AS contact_is_supplier,
    c.is_client                                     AS contact_is_client,
    COALESCE(c.email,    o.client_email)            AS contact_email,
    c.phone                                         AS contact_telefone,
    c.city                                          AS contact_cidade,
    c.state                                         AS contact_uf,
    o.client_ie                                     AS contact_ie

FROM bling_orders o
LEFT JOIN bling_contacts c ON c.id = o.client_id::bigint
WHERE o.client_id ~ '^\d+$'

UNION ALL

-- ── NF-e ────────────────────────────────────────────────────────────────────
SELECT
    'NF-e',
    n.id,

    CASE n.situation
        WHEN '1' THEN 'Pendente'
        WHEN '6' THEN 'Autorizada'
        WHEN '9' THEN 'Inutilizada'
        ELSE n.situation
    END,
    n.situation,

    n.total,
    n.total,

    n.issue_date,
    NULL::date,
    n.created_at,
    n.updated_at,

    NULL::text,   -- order_number
    NULL::text,   -- shipping_address
    NULL::text,   -- billing_address

    n.numero,
    n.serie,

    NULL::text,   -- description
    NULL::text,   -- competency
    NULL::text,   -- category

    n.contact_id,
    COALESCE(c.name, n.contact_name),
    c.document,
    c.person_type,
    c.is_supplier,
    c.is_client,
    c.email,
    c.phone,
    c.city,
    c.state,
    NULL::text    -- contact_ie

FROM bling_nfe n
LEFT JOIN bling_contacts c ON c.id = n.contact_id

UNION ALL

-- ── Contas a receber ─────────────────────────────────────────────────────────
SELECT
    'Conta Receber',
    cr.id,

    CASE cr.status
        WHEN '1' THEN 'Aberto'
        WHEN '2' THEN 'Recebido'
        WHEN '5' THEN 'Parcial'
        ELSE cr.status
    END,
    cr.status,

    cr.value,
    cr.value,

    cr.due_date,
    cr.due_date,
    cr.created_at,
    cr.updated_at,

    NULL::text,   -- order_number
    NULL::text,   -- shipping_address
    NULL::text,   -- billing_address

    NULL::text,   -- nfe_numero
    NULL::text,   -- nfe_serie

    cr.description,
    cr.competency,
    cr.category,

    cr.contact_id,
    COALESCE(c.name, cr.contact_name),
    c.document,
    c.person_type,
    c.is_supplier,
    c.is_client,
    c.email,
    c.phone,
    c.city,
    c.state,
    NULL::text    -- contact_ie

FROM bling_contas_receber cr
LEFT JOIN bling_contacts c ON c.id = cr.contact_id

UNION ALL

-- ── Contas a pagar ───────────────────────────────────────────────────────────
SELECT
    'Conta Pagar',
    cp.id,

    CASE cp.status
        WHEN '1' THEN 'Aberto'
        WHEN '2' THEN 'Pago'
        WHEN '5' THEN 'Parcial'
        ELSE cp.status
    END,
    cp.status,

    -cp.value,    -- negativo: saída de caixa
    cp.value,     -- valor_original sempre positivo

    cp.due_date,
    cp.due_date,
    cp.created_at,
    cp.updated_at,

    NULL::text,   -- order_number
    NULL::text,   -- shipping_address
    NULL::text,   -- billing_address

    NULL::text,   -- nfe_numero
    NULL::text,   -- nfe_serie

    cp.description,
    cp.competency,
    cp.category,

    cp.supplier_id,
    COALESCE(c.name, cp.supplier_name),
    c.document,
    c.person_type,
    c.is_supplier,
    c.is_client,
    c.email,
    c.phone,
    c.city,
    c.state,
    NULL::text    -- contact_ie

FROM bling_contas_pagar cp
LEFT JOIN bling_contacts c ON c.id = cp.supplier_id;


-- ---------------------------------------------------------------------------
-- Permissões: executar como superuser após criar as views
-- ---------------------------------------------------------------------------

GRANT SELECT ON vw_bling_contato_resumo TO api_user;
GRANT SELECT ON vw_bling_movimentos     TO api_user;
