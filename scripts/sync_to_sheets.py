"""
scripts/sync_to_sheets.py
Sincroniza dados do Bling para o Google Sheets — uma aba por entidade.

Abas geradas:
    Pedidos          → bling_orders × bling_contacts
    NF-e             → bling_nfe × bling_contacts
    Contas Receber   → bling_contas_receber × bling_contacts
    Contas Pagar     → bling_contas_pagar × bling_contacts
    Contatos         → bling_contacts
    _log             → histórico de execuções

.env necessário:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
    GSHEETS_SPREADSHEET_ID=1AbCdEf...
    GSHEETS_CREDENTIALS=path/to/service_account.json

Uso:
    python scripts/sync_to_sheets.py                    # todas as entidades
    python scripts/sync_to_sheets.py --entity pedidos   # só pedidos
    python scripts/sync_to_sheets.py --dry-run          # sem gravar no Sheets
"""

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 5_000
RETRY_WAIT  = 61


def _col_letter(n: int) -> str:
    result = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        result = chr(65 + r) + result
    return result


# ---------------------------------------------------------------------------
# Definição das entidades
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    key: str
    tab: str
    headers: list[str]
    sql: str


ENTITIES: list[Entity] = [

    Entity(
        key="pedidos",
        tab="Pedidos",
        headers=[
            "ID Bling", "Nº Pedido", "Status", "Status Raw",
            "Valor (R$)", "Data", "Criado em", "Atualizado em",
            "End. Entrega", "End. Cobrança",
            "Contact ID", "Nome Contato", "Documento", "Tipo Pessoa",
            "Fornecedor", "Cliente", "E-mail", "Telefone", "Cidade", "UF", "IE",
        ],
        sql="""
            SELECT
                o.id::text,
                o.order_number,
                CASE o.status
                    WHEN '6'  THEN 'Em Aberto'
                    WHEN '9'  THEN 'Atendido'
                    WHEN '12' THEN 'Cancelado'
                    WHEN '15' THEN 'Em Andamento'
                    WHEN '21' THEN 'Verificado'
                    ELSE o.status
                END,
                o.status,
                o.total,
                o.created_at::date,
                o.created_at,
                o.updated_at,
                o.shipping_address,
                o.billing_address,
                o.client_id,
                COALESCE(c.name,     o.client_name),
                COALESCE(c.document, o.client_cpf_cnpj),
                c.person_type,
                c.is_supplier,
                c.is_client,
                COALESCE(c.email, o.client_email),
                c.phone,
                c.city,
                c.state,
                o.client_ie
            FROM bling_orders o
            LEFT JOIN bling_contacts c ON c.id = o.client_id::bigint
            WHERE o.client_id ~ '^[0-9]+$'
            ORDER BY o.created_at DESC
        """,
    ),

    Entity(
        key="nfe",
        tab="NF-e",
        headers=[
            "ID Bling", "NF Número", "NF Série", "Status", "Status Raw",
            "Valor (R$)", "Data Emissão", "Criado em", "Atualizado em",
            "Contact ID", "Nome Contato", "Documento", "Tipo Pessoa",
            "Fornecedor", "Cliente", "E-mail", "Telefone", "Cidade", "UF",
        ],
        sql="""
            SELECT
                n.id::text,
                n.numero,
                n.serie,
                CASE n.situation
                    WHEN '1' THEN 'Pendente'
                    WHEN '6' THEN 'Autorizada'
                    WHEN '9' THEN 'Inutilizada'
                    ELSE n.situation
                END,
                n.situation,
                n.total,
                n.issue_date,
                n.created_at,
                n.updated_at,
                n.contact_id::text,
                COALESCE(c.name, n.contact_name),
                c.document,
                c.person_type,
                c.is_supplier,
                c.is_client,
                c.email,
                c.phone,
                c.city,
                c.state
            FROM bling_nfe n
            LEFT JOIN bling_contacts c ON c.id = n.contact_id
            ORDER BY n.issue_date DESC NULLS LAST
        """,
    ),

    Entity(
        key="receber",
        tab="Contas Receber",
        headers=[
            "ID Bling", "Descrição", "Status", "Status Raw",
            "Valor (R$)", "Vencimento", "Competência", "Categoria",
            "Criado em", "Atualizado em",
            "Contact ID", "Nome Contato", "Documento", "Tipo Pessoa",
            "Fornecedor", "Cliente", "E-mail", "Telefone", "Cidade", "UF",
        ],
        sql="""
            SELECT
                cr.id::text,
                cr.description,
                CASE cr.status
                    WHEN '1' THEN 'Aberto'
                    WHEN '2' THEN 'Recebido'
                    WHEN '5' THEN 'Parcial'
                    ELSE cr.status
                END,
                cr.status,
                cr.value,
                cr.due_date,
                cr.competency,
                cr.category,
                cr.created_at,
                cr.updated_at,
                cr.contact_id::text,
                COALESCE(c.name, cr.contact_name),
                c.document,
                c.person_type,
                c.is_supplier,
                c.is_client,
                c.email,
                c.phone,
                c.city,
                c.state
            FROM bling_contas_receber cr
            LEFT JOIN bling_contacts c ON c.id = cr.contact_id
            ORDER BY cr.due_date DESC NULLS LAST
        """,
    ),

    Entity(
        key="pagar",
        tab="Contas Pagar",
        headers=[
            "ID Bling", "Descrição", "Status", "Status Raw",
            "Valor (R$)", "Vencimento", "Competência", "Categoria",
            "Criado em", "Atualizado em",
            "Supplier ID", "Nome Fornecedor", "Documento", "Tipo Pessoa",
            "Fornecedor", "Cliente", "E-mail", "Telefone", "Cidade", "UF",
        ],
        sql="""
            SELECT
                cp.id::text,
                cp.description,
                CASE cp.status
                    WHEN '1' THEN 'Aberto'
                    WHEN '2' THEN 'Pago'
                    WHEN '5' THEN 'Parcial'
                    ELSE cp.status
                END,
                cp.status,
                cp.value,
                cp.due_date,
                cp.competency,
                cp.category,
                cp.created_at,
                cp.updated_at,
                cp.supplier_id::text,
                COALESCE(c.name, cp.supplier_name),
                c.document,
                c.person_type,
                c.is_supplier,
                c.is_client,
                c.email,
                c.phone,
                c.city,
                c.state
            FROM bling_contas_pagar cp
            LEFT JOIN bling_contacts c ON c.id = cp.supplier_id
            ORDER BY cp.due_date DESC NULLS LAST
        """,
    ),

    Entity(
        key="contatos",
        tab="Contatos",
        headers=[
            "ID Bling", "Código Bling", "Nome", "Nome Fantasia",
            "Documento", "Tipo Pessoa", "Fornecedor", "Cliente",
            "Tipos de Contato", "Estrangeiro", "País",
            "E-mail", "E-mail NF-e", "Telefone", "Celular",
            "Endereço", "Número", "Complemento", "Bairro", "CEP", "Cidade", "UF",
            "Endereço Cobrança", "Cidade Cobrança", "UF Cobrança", "CEP Cobrança",
            "IE", "Indicador IE", "Inscrição Municipal", "RG", "Órgão Emissor",
            "Órgão Público", "Data Nascimento", "Sexo", "Naturalidade",
            "Limite Crédito", "Condição Pagamento", "Categoria Financeira",
            "Vendedor ID", "Qtd Pessoas de Contato",
            "Situação", "Criado em", "Atualizado em",
        ],
        sql="""
            SELECT
                c.id::text,
                c.raw_json ->> 'codigo',
                c.name,
                NULLIF(c.raw_json ->> 'fantasia', ''),
                c.document,
                c.person_type,
                c.is_supplier,
                c.is_client,
                (
                    SELECT string_agg(t ->> 'descricao', ', ')
                    FROM jsonb_array_elements(COALESCE(c.raw_json -> 'tiposContato', '[]'::jsonb)) t
                ),
                (c.raw_json ->> 'tipo' = 'E'),
                NULLIF(c.raw_json -> 'pais' ->> 'nome', ''),
                c.email,
                NULLIF(c.raw_json ->> 'emailNotaFiscal', ''),
                c.phone,
                NULLIF(c.raw_json ->> 'celular', ''),
                NULLIF(c.raw_json -> 'endereco' -> 'geral' ->> 'endereco', ''),
                NULLIF(c.raw_json -> 'endereco' -> 'geral' ->> 'numero', ''),
                NULLIF(c.raw_json -> 'endereco' -> 'geral' ->> 'complemento', ''),
                NULLIF(c.raw_json -> 'endereco' -> 'geral' ->> 'bairro', ''),
                NULLIF(c.raw_json -> 'endereco' -> 'geral' ->> 'cep', ''),
                c.city,
                c.state,
                NULLIF(c.raw_json -> 'endereco' -> 'cobranca' ->> 'endereco', ''),
                NULLIF(c.raw_json -> 'endereco' -> 'cobranca' ->> 'municipio', ''),
                NULLIF(c.raw_json -> 'endereco' -> 'cobranca' ->> 'uf', ''),
                NULLIF(c.raw_json -> 'endereco' -> 'cobranca' ->> 'cep', ''),
                NULLIF(c.raw_json ->> 'ie', ''),
                CASE c.raw_json ->> 'indicadorIe'
                    WHEN '1' THEN 'Contribuinte ICMS'
                    WHEN '2' THEN 'Contribuinte isento'
                    WHEN '9' THEN 'Não contribuinte'
                    ELSE NULLIF(c.raw_json ->> 'indicadorIe', '')
                END,
                NULLIF(c.raw_json ->> 'inscricaoMunicipal', ''),
                NULLIF(c.raw_json ->> 'rg', ''),
                NULLIF(c.raw_json ->> 'orgaoEmissor', ''),
                NULLIF(c.raw_json ->> 'orgaoPublico', ''),
                NULLIF(c.raw_json -> 'dadosAdicionais' ->> 'dataNascimento', '0000-00-00'),
                NULLIF(c.raw_json -> 'dadosAdicionais' ->> 'sexo', ''),
                NULLIF(c.raw_json -> 'dadosAdicionais' ->> 'naturalidade', ''),
                NULLIF((c.raw_json -> 'financeiro' ->> 'limiteCredito')::numeric, 0),
                NULLIF(c.raw_json -> 'financeiro' ->> 'condicaoPagamento', ''),
                NULLIF((c.raw_json -> 'financeiro' -> 'categoria' ->> 'id')::text, '0'),
                NULLIF((c.raw_json -> 'vendedor' ->> 'id')::text, '0'),
                jsonb_array_length(COALESCE(c.raw_json -> 'pessoasContato', '[]'::jsonb)),
                CASE c.raw_json ->> 'situacao'
                    WHEN 'A' THEN 'Ativo'
                    WHEN 'I' THEN 'Inativo'
                    ELSE c.raw_json ->> 'situacao'
                END,
                c.created_at,
                c.updated_at
            FROM bling_contacts c
            ORDER BY c.name
        """,
    ),
]

ENTITY_MAP = {e.key: e for e in ENTITIES}

# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------

def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        f = float(v)
        return int(f) if f == int(f) else f
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v


def _fetch(sql: str) -> list[list]:
    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [[_fmt(cell) for cell in row] for row in cur.fetchall()]
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------

def _build_client(credentials_path: str | None):
    import gspread
    from google.oauth2.service_account import Credentials
    import google.auth

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]
    creds_file = credentials_path or os.environ.get("GSHEETS_CREDENTIALS")
    if creds_file:
        creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
    else:
        creds, _ = google.auth.default(scopes=scopes)
    return gspread.authorize(creds)


def _get_or_create_tab(spreadsheet, tab_name: str, n_rows: int, n_cols: int):
    import gspread
    try:
        ws = spreadsheet.worksheet(tab_name)
        ws.resize(rows=n_rows, cols=n_cols)
        return ws
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=n_rows, cols=n_cols)
        logger.info("Aba '%s' criada.", tab_name)
        return ws


def _write_batch(ws, data: list[list], start_row: int, last_col: str):
    import gspread.exceptions
    end_row = start_row + len(data) - 1
    range_notation = f"A{start_row}:{last_col}{end_row}"
    for attempt in range(3):
        try:
            ws.update(values=data, range_name=range_notation, value_input_option="RAW")
            return
        except gspread.exceptions.APIError as exc:
            if "429" in str(exc) and attempt < 2:
                logger.warning("Rate limit. Aguardando %ss...", RETRY_WAIT)
                time.sleep(RETRY_WAIT)
            else:
                raise


def _sync_tab(ws, headers: list[str], rows: list[list]):
    last_col = _col_letter(len(headers))
    logger.info("Limpando aba '%s'...", ws.title)
    ws.clear()

    all_data = [headers] + rows
    total = len(all_data)

    for start in range(0, total, BATCH_SIZE):
        chunk = all_data[start: start + BATCH_SIZE]
        _write_batch(ws, chunk, start_row=start + 1, last_col=last_col)
        logger.info("  %s / %s linhas", min(start + len(chunk), total), total)

    ws.format(f"A1:{last_col}1", {
        "backgroundColor": {"red": 0.122, "green": 0.306, "blue": 0.486},
        "textFormat": {
            "bold": True,
            "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
            "fontSize": 10,
        },
        "horizontalAlignment": "CENTER",
    })
    ws.freeze(rows=1)
    logger.info("'%s' sincronizada — %s linhas.", ws.title, total - 1)


def _append_log(spreadsheet, entries: list[dict]):
    import gspread
    log_name = "_log"
    try:
        log_ws = spreadsheet.worksheet(log_name)
    except gspread.WorksheetNotFound:
        log_ws = spreadsheet.add_worksheet(title=log_name, rows=500, cols=5)
        log_ws.update(
            values=[["Data/Hora", "Aba", "Linhas", "Tempo (s)", "Status"]],
            range_name="A1:E1",
        )
        log_ws.format("A1:E1", {"textFormat": {"bold": True}})

    for e in entries:
        log_ws.append_row(
            [datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             e["tab"], e["rows"], round(e["elapsed"], 1), e["status"]],
            value_input_option="RAW",
        )

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(
    spreadsheet_id: str,
    credentials_path: str | None,
    entity_keys: list[str],
    dry_run: bool,
):
    targets = [ENTITY_MAP[k] for k in entity_keys]

    # 1. Buscar todos os dados primeiro
    fetched: list[tuple[Entity, list[list]]] = []
    for entity in targets:
        logger.info("[%s] Buscando dados...", entity.tab)
        rows = _fetch(entity.sql)
        logger.info("[%s] %s linhas.", entity.tab, len(rows))
        fetched.append((entity, rows))

    if dry_run:
        logger.info("--dry-run: nenhum dado enviado.")
        return

    # 2. Conectar ao Sheets e sincronizar
    logger.info("Conectando ao Google Sheets...")
    gc = _build_client(credentials_path)
    spreadsheet = gc.open_by_key(spreadsheet_id)

    log_entries = []
    for entity, rows in fetched:
        t0 = time.monotonic()
        ws = _get_or_create_tab(spreadsheet, entity.tab, len(rows) + 1, len(entity.headers))
        _sync_tab(ws, entity.headers, rows)
        elapsed = time.monotonic() - t0
        log_entries.append({"tab": entity.tab, "rows": len(rows), "elapsed": elapsed, "status": "OK"})

    _append_log(spreadsheet, log_entries)
    logger.info("Concluído.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bling → Google Sheets (abas por entidade)")
    parser.add_argument(
        "--sheet-id",
        default=os.environ.get("GSHEETS_SPREADSHEET_ID"),
        help="ID da planilha (ou GSHEETS_SPREADSHEET_ID no .env)",
    )
    parser.add_argument(
        "--credentials",
        default=os.environ.get("GSHEETS_CREDENTIALS"),
        help="Caminho do service_account.json (ou GSHEETS_CREDENTIALS no .env)",
    )
    parser.add_argument(
        "--entity",
        choices=list(ENTITY_MAP.keys()) + ["all"],
        default="all",
        help="Entidade a sincronizar: all | pedidos | nfe | receber | pagar | contatos (default: all)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.sheet_id:
        parser.error("Informe --sheet-id ou GSHEETS_SPREADSHEET_ID no .env")

    keys = list(ENTITY_MAP.keys()) if args.entity == "all" else [args.entity]

    main(
        spreadsheet_id=args.sheet_id,
        credentials_path=args.credentials,
        entity_keys=keys,
        dry_run=args.dry_run,
    )
