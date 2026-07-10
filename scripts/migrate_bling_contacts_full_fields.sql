-- migrate_bling_contacts_full_fields.sql
--
-- Adiciona colunas fisicas para os campos ricos do contato Bling (pais, IE,
-- endereco completo, financeiro, etc.) e faz backfill instantaneo a partir do
-- raw_json ja armazenado em cada linha (nenhuma chamada nova a API do Bling).
--
-- Requer privilegio de owner da tabela (api_user nao tem ALTER TABLE).
-- Rode com uma credencial admin/postgres:
--   psql "host=34.44.240.153 port=5432 dbname=postgres user=postgres" \
--        -f scripts/migrate_bling_contacts_full_fields.sql
--
-- Idempotente: pode ser rodado mais de uma vez sem erro (IF NOT EXISTS).

BEGIN;

ALTER TABLE bling_contacts
    ADD COLUMN IF NOT EXISTS internal_code           text,
    ADD COLUMN IF NOT EXISTS trade_name               text,
    ADD COLUMN IF NOT EXISTS contact_types             text,
    ADD COLUMN IF NOT EXISTS country                   text,
    ADD COLUMN IF NOT EXISTS is_foreign                boolean,
    ADD COLUMN IF NOT EXISTS email_nfe                 text,
    ADD COLUMN IF NOT EXISTS cell_phone                text,
    ADD COLUMN IF NOT EXISTS street                    text,
    ADD COLUMN IF NOT EXISTS street_number             text,
    ADD COLUMN IF NOT EXISTS complement                text,
    ADD COLUMN IF NOT EXISTS neighborhood              text,
    ADD COLUMN IF NOT EXISTS zip_code                  text,
    ADD COLUMN IF NOT EXISTS billing_street            text,
    ADD COLUMN IF NOT EXISTS billing_city              text,
    ADD COLUMN IF NOT EXISTS billing_state             text,
    ADD COLUMN IF NOT EXISTS billing_zip_code          text,
    ADD COLUMN IF NOT EXISTS state_registration        text,
    ADD COLUMN IF NOT EXISTS state_registration_status text,
    ADD COLUMN IF NOT EXISTS municipal_registration    text,
    ADD COLUMN IF NOT EXISTS rg                        text,
    ADD COLUMN IF NOT EXISTS issuing_agency            text,
    ADD COLUMN IF NOT EXISTS public_agency             text,
    ADD COLUMN IF NOT EXISTS birth_date                date,
    ADD COLUMN IF NOT EXISTS gender                    text,
    ADD COLUMN IF NOT EXISTS place_of_birth            text,
    ADD COLUMN IF NOT EXISTS credit_limit              numeric,
    ADD COLUMN IF NOT EXISTS payment_terms             text,
    ADD COLUMN IF NOT EXISTS financial_category_id     text,
    ADD COLUMN IF NOT EXISTS seller_id                 text,
    ADD COLUMN IF NOT EXISTS contact_persons_count     integer;

-- Backfill a partir do raw_json ja salvo (sem custo de API).
UPDATE bling_contacts SET
    internal_code             = NULLIF(raw_json ->> 'codigo', ''),
    trade_name                 = NULLIF(raw_json ->> 'fantasia', ''),
    contact_types               = (
        SELECT string_agg(t ->> 'descricao', ', ')
        FROM jsonb_array_elements(COALESCE(raw_json -> 'tiposContato', '[]'::jsonb)) t
    ),
    country                     = NULLIF(raw_json -> 'pais' ->> 'nome', ''),
    is_foreign                  = (raw_json ->> 'tipo' = 'E'),
    email_nfe                   = NULLIF(raw_json ->> 'emailNotaFiscal', ''),
    cell_phone                  = NULLIF(raw_json ->> 'celular', ''),
    street                      = NULLIF(raw_json -> 'endereco' -> 'geral' ->> 'endereco', ''),
    street_number               = NULLIF(raw_json -> 'endereco' -> 'geral' ->> 'numero', ''),
    complement                  = NULLIF(raw_json -> 'endereco' -> 'geral' ->> 'complemento', ''),
    neighborhood                = NULLIF(raw_json -> 'endereco' -> 'geral' ->> 'bairro', ''),
    zip_code                    = NULLIF(raw_json -> 'endereco' -> 'geral' ->> 'cep', ''),
    billing_street               = NULLIF(raw_json -> 'endereco' -> 'cobranca' ->> 'endereco', ''),
    billing_city                 = NULLIF(raw_json -> 'endereco' -> 'cobranca' ->> 'municipio', ''),
    billing_state                = NULLIF(raw_json -> 'endereco' -> 'cobranca' ->> 'uf', ''),
    billing_zip_code             = NULLIF(raw_json -> 'endereco' -> 'cobranca' ->> 'cep', ''),
    state_registration          = NULLIF(raw_json ->> 'ie', ''),
    state_registration_status  = CASE raw_json ->> 'indicadorIe'
        WHEN '1' THEN 'Contribuinte ICMS'
        WHEN '2' THEN 'Contribuinte isento'
        WHEN '9' THEN 'Nao contribuinte'
        ELSE NULLIF(raw_json ->> 'indicadorIe', '')
    END,
    municipal_registration      = NULLIF(raw_json ->> 'inscricaoMunicipal', ''),
    rg                           = NULLIF(raw_json ->> 'rg', ''),
    issuing_agency               = NULLIF(raw_json ->> 'orgaoEmissor', ''),
    public_agency                = NULLIF(raw_json ->> 'orgaoPublico', ''),
    birth_date                   = NULLIF(
        NULLIF(raw_json -> 'dadosAdicionais' ->> 'dataNascimento', '0000-00-00'), ''
    )::date,
    gender                       = NULLIF(raw_json -> 'dadosAdicionais' ->> 'sexo', ''),
    place_of_birth                = NULLIF(raw_json -> 'dadosAdicionais' ->> 'naturalidade', ''),
    credit_limit                 = NULLIF((raw_json -> 'financeiro' ->> 'limiteCredito')::numeric, 0),
    payment_terms                = NULLIF(raw_json -> 'financeiro' ->> 'condicaoPagamento', ''),
    financial_category_id       = NULLIF((raw_json -> 'financeiro' -> 'categoria' ->> 'id')::text, '0'),
    seller_id                    = NULLIF((raw_json -> 'vendedor' ->> 'id')::text, '0'),
    contact_persons_count       = jsonb_array_length(COALESCE(raw_json -> 'pessoasContato', '[]'::jsonb))
WHERE raw_json ? 'tipo';  -- so linhas ja enriquecidas com detalhe (tem 'tipo' no raw_json)

-- Permite que o api_user (usado pela aplicacao/fetcher) grave nessas colunas
-- em cargas futuras (o INSERT ... ON CONFLICT do upsert_contacts precisa disso).
GRANT SELECT, INSERT, UPDATE ON bling_contacts TO api_user;

COMMIT;

-- Verificacao pos-migracao:
-- SELECT count(*), count(*) FILTER (WHERE is_foreign) AS estrangeiros,
--        count(*) FILTER (WHERE country IS NOT NULL) AS com_pais
-- FROM bling_contacts;
