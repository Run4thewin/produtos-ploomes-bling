"""
blng_fetcher/main.py
Busca entidades do Bling e faz upsert no PostgreSQL.

Uso:
    python -m blng_fetcher.main                          # orders, 1 pagina
    python -m blng_fetcher.main --entity all --pages 999 # todas entidades
    python -m blng_fetcher.main --entity contacts --pages 5

Entidades: all | orders | contacts | nfe | pagar | receber | naturezas | produtos
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, date, timezone
from pathlib import Path

import httpx
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from app.clients.bling import BlingClient  # noqa: E402
from app.clients.rate_limit import DailyQuotaExceeded  # noqa: E402

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
        # endereco/financeiro/dadosAdicionais/tiposContato so vem no detalhe
        # (/contatos/{id}); a listagem nao traz esses campos.
        endereco = (c.get("endereco") or {}).get("geral") or {}
        cobranca = (c.get("endereco") or {}).get("cobranca") or {}
        financeiro = c.get("financeiro") or {}
        dados_adic = c.get("dadosAdicionais") or {}
        tipos_contato_list = c.get("tiposContato") or []
        tipos_contato = {(t.get("descricao") or "").strip().lower() for t in tipos_contato_list}
        indicador_ie = str(c.get("indicadorIe") or "")
        indicador_ie_label = {
            "1": "Contribuinte ICMS", "2": "Contribuinte isento", "9": "Nao contribuinte",
        }.get(indicador_ie, indicador_ie or None)

        rows.append((
            c.get("id"),
            c.get("nome"),
            c.get("numeroDocumento"),
            c.get("tipo"),
            "fornecedor" in tipos_contato,
            "cliente" in tipos_contato,
            c.get("email"),
            phone,
            endereco.get("municipio"),
            endereco.get("uf"),
            _parse_dt(c.get("dataCriacao")),
            _now(),
            json.dumps(c, ensure_ascii=False),
            c.get("codigo") or None,
            c.get("fantasia") or None,
            ", ".join(t.get("descricao") for t in tipos_contato_list if t.get("descricao")) or None,
            (c.get("pais") or {}).get("nome") or None,
            c.get("tipo") == "E",
            c.get("emailNotaFiscal") or None,
            c.get("celular") or None,
            endereco.get("endereco") or None,
            endereco.get("numero") or None,
            endereco.get("complemento") or None,
            endereco.get("bairro") or None,
            endereco.get("cep") or None,
            cobranca.get("endereco") or None,
            cobranca.get("municipio") or None,
            cobranca.get("uf") or None,
            cobranca.get("cep") or None,
            c.get("ie") or None,
            indicador_ie_label,
            c.get("inscricaoMunicipal") or None,
            c.get("rg") or None,
            c.get("orgaoEmissor") or None,
            c.get("orgaoPublico") or None,
            _parse_date(dados_adic.get("dataNascimento")),
            dados_adic.get("sexo") or None,
            dados_adic.get("naturalidade") or None,
            (financeiro.get("limiteCredito") or None),
            financeiro.get("condicaoPagamento") or None,
            str((financeiro.get("categoria") or {}).get("id") or "") or None,
            str((c.get("vendedor") or {}).get("id") or "") or None,
            len(c.get("pessoasContato") or []),
        ))

    sql = """
        INSERT INTO bling_contacts
            (id, name, document, person_type, is_supplier, is_client,
             email, phone, city, state, created_at, updated_at, raw_json,
             internal_code, trade_name, contact_types, country, is_foreign,
             email_nfe, cell_phone, street, street_number, complement,
             neighborhood, zip_code, billing_street, billing_city, billing_state,
             billing_zip_code, state_registration, state_registration_status,
             municipal_registration, rg, issuing_agency, public_agency,
             birth_date, gender, place_of_birth, credit_limit, payment_terms,
             financial_category_id, seller_id, contact_persons_count)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            name                       = EXCLUDED.name,
            document                   = EXCLUDED.document,
            person_type                = EXCLUDED.person_type,
            is_supplier                = EXCLUDED.is_supplier,
            is_client                  = EXCLUDED.is_client,
            email                      = EXCLUDED.email,
            phone                      = EXCLUDED.phone,
            city                       = EXCLUDED.city,
            state                      = EXCLUDED.state,
            updated_at                 = EXCLUDED.updated_at,
            raw_json                   = EXCLUDED.raw_json,
            internal_code              = EXCLUDED.internal_code,
            trade_name                 = EXCLUDED.trade_name,
            contact_types              = EXCLUDED.contact_types,
            country                    = EXCLUDED.country,
            is_foreign                 = EXCLUDED.is_foreign,
            email_nfe                  = EXCLUDED.email_nfe,
            cell_phone                 = EXCLUDED.cell_phone,
            street                     = EXCLUDED.street,
            street_number              = EXCLUDED.street_number,
            complement                 = EXCLUDED.complement,
            neighborhood               = EXCLUDED.neighborhood,
            zip_code                   = EXCLUDED.zip_code,
            billing_street             = EXCLUDED.billing_street,
            billing_city               = EXCLUDED.billing_city,
            billing_state              = EXCLUDED.billing_state,
            billing_zip_code           = EXCLUDED.billing_zip_code,
            state_registration         = EXCLUDED.state_registration,
            state_registration_status  = EXCLUDED.state_registration_status,
            municipal_registration     = EXCLUDED.municipal_registration,
            rg                         = EXCLUDED.rg,
            issuing_agency             = EXCLUDED.issuing_agency,
            public_agency              = EXCLUDED.public_agency,
            birth_date                 = EXCLUDED.birth_date,
            gender                     = EXCLUDED.gender,
            place_of_birth             = EXCLUDED.place_of_birth,
            credit_limit               = EXCLUDED.credit_limit,
            payment_terms              = EXCLUDED.payment_terms,
            financial_category_id      = EXCLUDED.financial_category_id,
            seller_id                  = EXCLUDED.seller_id,
            contact_persons_count      = EXCLUDED.contact_persons_count
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
# Upsert: produtos
# ---------------------------------------------------------------------------

def upsert_produtos(conn, produtos: list[dict]) -> int:
    produtos = _dedup(produtos)
    rows = []
    for p in produtos:
        tributacao = p.get("tributacao") or {}
        dimensoes = p.get("dimensoes") or {}
        rows.append((
            p.get("id"),
            p.get("codigo"),
            p.get("nome"),
            p.get("descricaoCurta"),
            float(p.get("preco", 0) or 0),
            p.get("situacao"),
            p.get("tipo"),
            p.get("formato"),
            p.get("marca"),
            tributacao.get("ncm"),
            p.get("pesoLiquido"),
            p.get("pesoBruto"),
            dimensoes.get("largura"),
            dimensoes.get("altura"),
            dimensoes.get("profundidade"),
            _now(),
            _now(),
            json.dumps(p, ensure_ascii=False),
        ))

    sql = """
        INSERT INTO bling_produtos
            (id, codigo, nome, descricao_curta, preco, situacao, tipo, formato,
             marca, ncm, peso_liquido, peso_bruto, largura, altura, profundidade,
             created_at, updated_at, raw_json)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            codigo          = EXCLUDED.codigo,
            nome            = EXCLUDED.nome,
            descricao_curta = EXCLUDED.descricao_curta,
            preco           = EXCLUDED.preco,
            situacao        = EXCLUDED.situacao,
            tipo            = EXCLUDED.tipo,
            formato         = EXCLUDED.formato,
            marca           = EXCLUDED.marca,
            ncm             = EXCLUDED.ncm,
            peso_liquido    = EXCLUDED.peso_liquido,
            peso_bruto      = EXCLUDED.peso_bruto,
            largura         = EXCLUDED.largura,
            altura          = EXCLUDED.altura,
            profundidade    = EXCLUDED.profundidade,
            updated_at      = EXCLUDED.updated_at,
            raw_json        = EXCLUDED.raw_json
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
    "produtos":  ("produtos",            upsert_produtos),
}


FETCH_PAGE_TRANSIENT_STATUS = {502, 503, 504}
FETCH_PAGE_RETRY_DELAYS = (2.0, 5.0, 10.0)


def _fetch_page(bling: BlingClient, endpoint: str, page: int, page_size: int) -> list[dict]:
    last_error: httpx.HTTPStatusError | None = None
    for attempt, delay in enumerate((0.0, *FETCH_PAGE_RETRY_DELAYS)):
        if delay:
            logger.warning(
                "Erro transitorio ao buscar pagina %s de %s; tentando de novo em %.0fs...",
                page, endpoint, delay,
            )
            time.sleep(delay)
        response = bling._request("GET", endpoint, params={"pagina": page, "limite": page_size})
        if response.status_code in FETCH_PAGE_TRANSIENT_STATUS:
            try:
                bling._raise_bling_error(response)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                continue
        bling._raise_bling_error(response)
        return response.json().get("data", [])
    raise last_error


def _fetch_nfe_detail(bling: BlingClient, nfe_id: int | str) -> dict | None:
    try:
        response = bling._request("GET", f"nfe/{nfe_id}")
        bling._raise_bling_error(response)
        return response.json().get("data")
    except DailyQuotaExceeded:
        raise
    except Exception as exc:
        logger.warning("Falha ao buscar detalhe da NF-e %s: %s", nfe_id, exc)
        return None


def _fetch_contact_detail(bling: BlingClient, contact_id: int | str) -> dict | None:
    # A listagem /contatos nao traz tipo/tiposContato/endereco/email; so o
    # detalhe (/contatos/{id}) tem esses campos, necessarios p/ is_supplier/is_client.
    try:
        return bling.get_contact(contact_id)
    except DailyQuotaExceeded:
        raise
    except Exception as exc:
        logger.warning("Falha ao buscar detalhe do contato %s: %s", contact_id, exc)
        return None


def _load_entity(
    bling: BlingClient,
    conn,
    endpoint: str,
    upsert_fn,
    entity_name: str,
    max_pages: int,
    page_size: int,
    start_page: int = 1,
) -> int:
    total = 0
    for page in range(start_page, start_page + max_pages):
        logger.info("[%s] Buscando pagina %s...", entity_name, page)
        try:
            items = _fetch_page(bling, endpoint, page, page_size)

            if entity_name == "nfe":
                enriched = []
                for item in items:
                    nfe_id = item.get("id")
                    detail = _fetch_nfe_detail(bling, nfe_id)
                    enriched.append(detail if detail else item)
                items = enriched
            elif entity_name == "contacts":
                enriched = []
                for item in items:
                    detail = _fetch_contact_detail(bling, item.get("id"))
                    enriched.append(detail if detail else item)
                items = enriched
        except DailyQuotaExceeded as exc:
            logger.warning(
                "[%s] %s. Parando na pagina %s (total ja gravado=%s). "
                "Reexecute amanha para continuar.",
                entity_name, exc, page, total,
            )
            break

        if not items:
            logger.info("[%s] Sem mais registros na pagina %s.", entity_name, page)
            break

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
        try:
            detail = _fetch_nfe_detail(bling, nfe_id)
        except DailyQuotaExceeded as exc:
            conn.commit()
            logger.warning(
                "[nfe-detail] %s. Parando em %s/%s. Reexecute amanha para continuar "
                "(itens ja atualizados sao pulados automaticamente).",
                exc, i - 1, total,
            )
            return updated
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

def main(entity: str = "orders", max_pages: int = 1, page_size: int = 100, start_page: int = 1):
    logger.info(
        "Iniciando carga — entity=%s max_pages=%s page_size=%s start_page=%s",
        entity, max_pages, page_size, start_page,
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
            total = _load_entity(bling, conn, endpoint, upsert_fn, name, max_pages, page_size, start_page)
            logger.info("[%s] Carga concluida. Total: %s registros.", name, total)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Bling entities to PostgreSQL")
    parser.add_argument(
        "--entity", default="orders",
        choices=["all", "orders", "contacts", "nfe", "nfe-detail", "pagar", "receber", "naturezas", "produtos"],
        help="Entidade a buscar (default: orders). Use nfe-detail para enriquecer NFs já no banco.",
    )
    parser.add_argument("--pages", type=int, default=1, help="Max de paginas (default: 1)")
    parser.add_argument("--page-size", type=int, default=100, help="Registros por pagina (default: 100)")
    parser.add_argument(
        "--start-page", type=int, default=1,
        help="Pagina inicial (default: 1). Use para retomar uma carga interrompida.",
    )
    args = parser.parse_args()
    main(entity=args.entity, max_pages=args.pages, page_size=args.page_size, start_page=args.start_page)
