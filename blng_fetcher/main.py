"""
blng_fetcher/main.py
Busca entidades do Bling e faz upsert no PostgreSQL.

Uso:
    python -m blng_fetcher.main                          # orders, 1 pagina
    python -m blng_fetcher.main --entity all --pages 999 # todas entidades
    python -m blng_fetcher.main --entity contacts --pages 5

Entidades: all | orders | contacts | nfe | pagar | receber
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, date, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from app.clients.bling import BlingClient  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    s = str(value)
    if s.startswith("0000"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    return None


def _parse_date(value) -> date | None:
    dt = _parse_dt(value)
    return dt.date() if dt else None


def _dedup(items: list[dict]) -> list[dict]:
    seen: dict = {}
    for item in items:
        seen[item.get("id")] = item
    return list(seen.values())


def _fmt_address(addr: dict) -> str | None:
    if not addr:
        return None
    parts = [
        addr.get("endereco"), addr.get("numero"), addr.get("complemento"),
        addr.get("bairro"), addr.get("municipio"), addr.get("uf"), addr.get("cep"),
    ]
    return ", ".join(p for p in parts if p) or None


# ---------------------------------------------------------------------------
# Upsert: orders
# ---------------------------------------------------------------------------

def upsert_orders(conn, orders: list[dict]) -> int:
    orders = _dedup(orders)
    rows = []
    for o in orders:
        contact = o.get("contato") or {}
        endereco = o.get("transporte", {}).get("enderecoEntrega") or {}
        situacao = o.get("situacao", {})
        rows.append((
            o.get("id"),
            str(o.get("numero", "")),
            str(situacao.get("id", "") if isinstance(situacao, dict) else situacao),
            float(o.get("totalProdutos", 0) or 0),
            _parse_dt(o.get("data")),
            _now(),
            str(contact.get("id", "") or ""),
            contact.get("nome"),
            contact.get("email"),
            contact.get("numeroDocumento"),
            contact.get("ie"),
            _fmt_address(endereco),
            None,
            json.dumps(o, ensure_ascii=False),
        ))

    sql = """
        INSERT INTO bling_orders
            (id, order_number, status, total, created_at, updated_at,
             client_id, client_name, client_email, client_cpf_cnpj, client_ie,
             shipping_address, billing_address, raw_json)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            order_number     = EXCLUDED.order_number,
            status           = EXCLUDED.status,
            total            = EXCLUDED.total,
            updated_at       = EXCLUDED.updated_at,
            client_id        = EXCLUDED.client_id,
            client_name      = EXCLUDED.client_name,
            client_email     = EXCLUDED.client_email,
            client_cpf_cnpj  = EXCLUDED.client_cpf_cnpj,
            client_ie        = EXCLUDED.client_ie,
            shipping_address = EXCLUDED.shipping_address,
            billing_address  = EXCLUDED.billing_address,
            raw_json         = EXCLUDED.raw_json
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Upsert: contacts
# ---------------------------------------------------------------------------

def upsert_contacts(conn, contacts: list[dict]) -> int:
    contacts = _dedup(contacts)
    rows = []
    for c in contacts:
        phone = c.get("telefone") or c.get("celular")
        endereco = c.get("endereco") or {}
        rows.append((
            c.get("id"),
            c.get("nome"),
            c.get("numeroDocumento"),
            c.get("tipo"),
            c.get("fornecedor"),
            c.get("cliente"),
            c.get("email"),
            phone,
            endereco.get("municipio"),
            endereco.get("uf"),
            _parse_dt(c.get("dataCriacao")),
            _now(),
            json.dumps(c, ensure_ascii=False),
        ))

    sql = """
        INSERT INTO bling_contacts
            (id, name, document, person_type, is_supplier, is_client,
             email, phone, city, state, created_at, updated_at, raw_json)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            name         = EXCLUDED.name,
            document     = EXCLUDED.document,
            person_type  = EXCLUDED.person_type,
            is_supplier  = EXCLUDED.is_supplier,
            is_client    = EXCLUDED.is_client,
            email        = EXCLUDED.email,
            phone        = EXCLUDED.phone,
            city         = EXCLUDED.city,
            state        = EXCLUDED.state,
            updated_at   = EXCLUDED.updated_at,
            raw_json     = EXCLUDED.raw_json
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Upsert: nfe
# ---------------------------------------------------------------------------

def upsert_nfe(conn, nfes: list[dict]) -> int:
    nfes = _dedup(nfes)
    rows = []
    for n in nfes:
        contato = n.get("contato") or {}
        total = n.get("valorNota")
        if total is None:
            itens = n.get("itens") or []
            total = sum(i.get("valorTotal", 0) for i in itens) or None
        rows.append((
            n.get("id"),
            str(n.get("numero", "")),
            str(n["serie"]) if n.get("serie") is not None else None,
            str(n.get("situacao", "")),
            contato.get("id"),
            contato.get("nome"),
            float(total) if total is not None else None,
            _parse_date(n.get("dataEmissao")),
            _now(),
            _now(),
            json.dumps(n, ensure_ascii=False),
        ))

    sql = """
        INSERT INTO bling_nfe
            (id, numero, serie, situation, contact_id, contact_name,
             total, issue_date, created_at, updated_at, raw_json)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            numero       = EXCLUDED.numero,
            serie        = EXCLUDED.serie,
            situation    = EXCLUDED.situation,
            contact_id   = EXCLUDED.contact_id,
            contact_name = EXCLUDED.contact_name,
            total        = EXCLUDED.total,
            issue_date   = EXCLUDED.issue_date,
            updated_at   = EXCLUDED.updated_at,
            raw_json     = EXCLUDED.raw_json
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Upsert: contas_pagar
# ---------------------------------------------------------------------------

def upsert_contas_pagar(conn, contas: list[dict]) -> int:
    contas = _dedup(contas)
    rows = []
    for c in contas:
        contato = c.get("contato") or {}
        categoria = c.get("categoria") or {}
        rows.append((
            c.get("id"),
            c.get("historico"),
            contato.get("id"),
            contato.get("nome"),
            _parse_date(c.get("vencimento")),
            float(c.get("valor", 0) or 0),
            str(c.get("situacao", "")),
            _parse_date(c.get("competencia")),
            categoria.get("descricao"),
            _now(),
            _now(),
            json.dumps(c, ensure_ascii=False),
        ))

    sql = """
        INSERT INTO bling_contas_pagar
            (id, description, supplier_id, supplier_name, due_date, value,
             status, competency, category, created_at, updated_at, raw_json)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            description   = EXCLUDED.description,
            supplier_id   = EXCLUDED.supplier_id,
            supplier_name = EXCLUDED.supplier_name,
            due_date      = EXCLUDED.due_date,
            value         = EXCLUDED.value,
            status        = EXCLUDED.status,
            competency    = EXCLUDED.competency,
            category      = EXCLUDED.category,
            updated_at    = EXCLUDED.updated_at,
            raw_json      = EXCLUDED.raw_json
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Upsert: contas_receber
# ---------------------------------------------------------------------------

def upsert_contas_receber(conn, contas: list[dict]) -> int:
    contas = _dedup(contas)
    rows = []
    for c in contas:
        contato = c.get("contato") or {}
        conta_contabil = c.get("contaContabil") or {}
        rows.append((
            c.get("id"),
            c.get("historico"),
            contato.get("id"),
            contato.get("nome"),
            _parse_date(c.get("vencimento")),
            float(c.get("valor", 0) or 0),
            str(c.get("situacao", "")),
            _parse_date(c.get("competencia")),
            conta_contabil.get("descricao"),
            _now(),
            _now(),
            json.dumps(c, ensure_ascii=False),
        ))

    sql = """
        INSERT INTO bling_contas_receber
            (id, description, contact_id, contact_name, due_date, value,
             status, competency, category, created_at, updated_at, raw_json)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            description  = EXCLUDED.description,
            contact_id   = EXCLUDED.contact_id,
            contact_name = EXCLUDED.contact_name,
            due_date     = EXCLUDED.due_date,
            value        = EXCLUDED.value,
            status       = EXCLUDED.status,
            competency   = EXCLUDED.competency,
            category     = EXCLUDED.category,
            updated_at   = EXCLUDED.updated_at,
            raw_json     = EXCLUDED.raw_json
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Upsert: naturezas_operacao
# ---------------------------------------------------------------------------

def upsert_naturezas(conn, naturezas: list[dict]) -> int:
    naturezas = _dedup(naturezas)
    rows = []
    for n in naturezas:
        rows.append((
            n.get("id"),
            n.get("descricao"),
            n.get("situacao"),
            bool(n.get("padrao")),
            _now(),
            _now(),
            json.dumps(n, ensure_ascii=False),
        ))

    sql = """
        INSERT INTO bling_naturezas_operacao
            (id, descricao, situacao, padrao, created_at, updated_at, raw_json)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            descricao  = EXCLUDED.descricao,
            situacao   = EXCLUDED.situacao,
            padrao     = EXCLUDED.padrao,
            updated_at = EXCLUDED.updated_at,
            raw_json   = EXCLUDED.raw_json
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Fetch + load generic
# ---------------------------------------------------------------------------

ENTITIES: dict[str, tuple[str, callable]] = {
    "orders":    ("pedidos/vendas",      upsert_orders),
    "contacts":  ("contatos",            upsert_contacts),
    "nfe":       ("nfe",                 upsert_nfe),
    "pagar":     ("contas/pagar",        upsert_contas_pagar),
    "receber":   ("contas/receber",      upsert_contas_receber),
    "naturezas": ("naturezas-operacoes", upsert_naturezas),
}


def _fetch_page(bling: BlingClient, endpoint: str, page: int, page_size: int) -> list[dict]:
    response = bling._request("GET", endpoint, params={"pagina": page, "limite": page_size})
    bling._raise_bling_error(response)
    return response.json().get("data", [])


def _fetch_nfe_detail(bling: BlingClient, nfe_id: int | str) -> dict | None:
    try:
        response = bling._request("GET", f"nfe/{nfe_id}")
        bling._raise_bling_error(response)
        return response.json().get("data")
    except Exception as exc:
        logger.warning("Falha ao buscar detalhe da NF-e %s: %s", nfe_id, exc)
        return None


def _load_entity(
    bling: BlingClient,
    conn,
    endpoint: str,
    upsert_fn,
    entity_name: str,
    max_pages: int,
    page_size: int,
) -> int:
    total = 0
    for page in range(1, max_pages + 1):
        logger.info("[%s] Buscando pagina %s...", entity_name, page)
        items = _fetch_page(bling, endpoint, page, page_size)
        if not items:
            logger.info("[%s] Sem mais registros na pagina %s.", entity_name, page)
            break

        if entity_name == "nfe":
            enriched = []
            for item in items:
                nfe_id = item.get("id")
                detail = _fetch_nfe_detail(bling, nfe_id)
                enriched.append(detail if detail else item)
            items = enriched

        inserted = upsert_fn(conn, items)
        total += inserted
        logger.info("[%s]   -> %s registros (total=%s)", entity_name, inserted, total)
        if len(items) < page_size:
            logger.info("[%s] Ultima pagina atingida.", entity_name)
            break
    return total


# ---------------------------------------------------------------------------
# Backfill: busca detalhe /nfe/{id} para cada registro já no banco
# ---------------------------------------------------------------------------

def _load_nfe_details(bling: BlingClient, conn, batch_size: int = 50) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM bling_nfe
            WHERE raw_json::jsonb ->> 'xml' IS NULL
            ORDER BY id
        """)
        ids = [row[0] for row in cur.fetchall()]

    total = len(ids)
    logger.info("[nfe-detail] %s notas encontradas no banco.", total)

    updated = 0
    for i, nfe_id in enumerate(ids, 1):
        detail = _fetch_nfe_detail(bling, nfe_id)
        if not detail:
            logger.warning("[nfe-detail] Sem detalhe para id=%s, pulando.", nfe_id)
            continue

        contato = detail.get("contato") or {}
        total_val = detail.get("valorNota")
        if total_val is None:
            itens = detail.get("itens") or []
            total_val = sum(it.get("valorTotal", 0) for it in itens) or None

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE bling_nfe SET
                    numero       = %s,
                    serie        = %s,
                    situation    = %s,
                    contact_id   = %s,
                    contact_name = %s,
                    total        = %s,
                    issue_date   = %s,
                    updated_at   = %s,
                    raw_json     = %s
                WHERE id = %s
                """,
                (
                    str(detail.get("numero", "")),
                    str(detail["serie"]) if detail.get("serie") is not None else None,
                    str(detail.get("situacao", "")),
                    contato.get("id"),
                    contato.get("nome"),
                    float(total_val) if total_val is not None else None,
                    _parse_date(detail.get("dataEmissao")),
                    _now(),
                    json.dumps(detail, ensure_ascii=False),
                    nfe_id,
                ),
            )

        if i % batch_size == 0:
            conn.commit()
            logger.info("[nfe-detail] %s/%s processadas...", i, total)

    conn.commit()
    logger.info("[nfe-detail] Concluido. %s notas atualizadas.", updated)
    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(entity: str = "orders", max_pages: int = 1, page_size: int = 100):
    logger.info(
        "Iniciando carga — entity=%s max_pages=%s page_size=%s",
        entity, max_pages, page_size,
    )

    bling = BlingClient()
    conn = get_db_conn()
    logger.info("Conectado ao banco %s@%s", os.environ["DB_NAME"], os.environ["DB_HOST"])

    if entity == "nfe-detail":
        try:
            _load_nfe_details(bling, conn)
        finally:
            conn.close()
        return

    targets = list(ENTITIES.items()) if entity == "all" else [(entity, ENTITIES[entity])]

    try:
        for name, (endpoint, upsert_fn) in targets:
            total = _load_entity(bling, conn, endpoint, upsert_fn, name, max_pages, page_size)
            logger.info("[%s] Carga concluida. Total: %s registros.", name, total)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Bling entities to PostgreSQL")
    parser.add_argument(
        "--entity", default="orders",
        choices=["all", "orders", "contacts", "nfe", "nfe-detail", "pagar", "receber", "naturezas"],
        help="Entidade a buscar (default: orders). Use nfe-detail para enriquecer NFs já no banco.",
    )
    parser.add_argument("--pages", type=int, default=1, help="Max de paginas (default: 1)")
    parser.add_argument("--page-size", type=int, default=100, help="Registros por pagina (default: 100)")
    args = parser.parse_args()
    main(entity=args.entity, max_pages=args.pages, page_size=args.page_size)
