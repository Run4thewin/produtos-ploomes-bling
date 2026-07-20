"""
blng_fetcher/engine.py
Motor generico de carga: fetch paginado -> hash -> diff -> historico -> upsert.
Dirigido por EntitySpec (blng_fetcher/specs). Substitui as funcoes upsert_*
quase identicas do main.py antigo.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import httpx
from psycopg2.extras import execute_values

from app.clients.bling import BlingClient
from app.clients.rate_limit import DailyQuotaExceeded

from .specs.base import EntitySpec, _dig, _now

logger = logging.getLogger(__name__)

FETCH_PAGE_TRANSIENT_STATUS = {502, 503, 504}
FETCH_PAGE_RETRY_DELAYS = (2.0, 5.0, 10.0)


@dataclass
class LoadStats:
    entity: str
    pages: int = 0
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    history_rows: int = 0
    detail_requests: int = 0
    status: str = "ok"          # ok | quota | error | partial
    last_page: int | None = None
    completed: bool = False      # percorreu ate a ultima pagina sem erro
    seen_ids: set = field(default_factory=set)  # p/ mark_deleted em full sweep


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_page(bling: BlingClient, endpoint: str, page: int, page_size: int,
               extra_params: dict | None = None) -> list[dict]:
    params = {"pagina": page, "limite": page_size, **(extra_params or {})}
    last_error: httpx.HTTPStatusError | None = None
    for delay in (0.0, *FETCH_PAGE_RETRY_DELAYS):
        if delay:
            logger.warning(
                "Erro transitorio ao buscar pagina %s de %s; tentando de novo em %.0fs...",
                page, endpoint, delay,
            )
            time.sleep(delay)
        response = bling._request("GET", endpoint, params=params)
        if response.status_code in FETCH_PAGE_TRANSIENT_STATUS:
            try:
                bling._raise_bling_error(response)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                continue
        bling._raise_bling_error(response)
        data = response.json().get("data", [])
        if isinstance(data, dict):  # singletons (ex.: empresas/me/dados-basicos)
            return [data]
        return data or []
    raise last_error


def fetch_detail(bling: BlingClient, spec: EntitySpec, item_id) -> dict | None:
    try:
        response = bling._request("GET", spec.detail_endpoint.format(id=item_id))
        bling._raise_bling_error(response)
        return response.json().get("data")
    except DailyQuotaExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - detalhe com falha nao aborta a pagina
        logger.warning("[%s] Falha ao buscar detalhe %s: %s", spec.name, item_id, exc)
        return None


# ---------------------------------------------------------------------------
# Hash / canonizacao / diff
# ---------------------------------------------------------------------------

def compute_source_hash(item: dict) -> str:
    canonical = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def canon(value: Any) -> str | None:
    """Normaliza um valor para comparacao/gravacao no historico (text)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        try:
            return format(Decimal(str(value)).normalize(), "f")
        except InvalidOperation:
            return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def diff_row(spec: EntitySpec, old: dict, new: dict) -> list[tuple[str, str | None, str | None]]:
    """[(coluna, old_canon, new_canon)] apenas para colunas auditadas que mudaram."""
    changes = []
    for column in spec.audited_columns:
        old_c = canon(old.get(column))
        new_c = canon(new.get(column))
        if old_c != new_c:
            changes.append((column, old_c, new_c))
    return changes


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------

def _item_id(spec: EntitySpec, item: dict):
    """Id do item conforme a spec (ex.: estoques/saldos usa produto.id)."""
    return _dig(item, spec.id_path)


def entity_key(spec: EntitySpec, row: dict) -> str:
    return ":".join(str(row.get(c)) for c in spec.conflict_columns)


def select_existing(conn, spec: EntitySpec, ids: list) -> dict:
    """{id: {source_hash, deleted_at, <colunas auditadas>}} dos ids informados."""
    if not ids:
        return {}
    if spec.conflict_columns != ("id",):
        raise NotImplementedError(
            f"{spec.name}: select_existing p/ PK composta e' tratado pelo loader dedicado")
    columns = ["id", "source_hash", "deleted_at", *spec.audited_columns]
    sql = f'SELECT {", ".join(columns)} FROM {spec.table} WHERE id = ANY(%s)'
    with conn.cursor() as cur:
        cur.execute(sql, (list(ids),))
        rows = cur.fetchall()
    return {row[0]: dict(zip(columns, row)) for row in rows}


def build_upsert_sql(spec: EntitySpec) -> str:
    field_cols = [f.column for f in spec.fields]
    insert_cols = ["id", *field_cols, "created_at", "updated_at",
                   "raw_json", "source_hash", "deleted_at"]
    update_cols = [*field_cols, "updated_at", "raw_json", "source_hash", "deleted_at"]
    conflict = ", ".join(spec.conflict_columns)
    set_clause = ",\n            ".join(
        f"{c} = EXCLUDED.{c}" for c in update_cols)
    return (
        f"INSERT INTO {spec.table} ({', '.join(insert_cols)})\n"
        f"        VALUES %s\n"
        f"        ON CONFLICT ({conflict}) DO UPDATE SET\n"
        f"            {set_clause}"
    )


def upsert_rows(conn, spec: EntitySpec, prepared: list[dict]) -> int:
    """prepared: [{id, values(dict col->valor), created_at, raw_json, source_hash}]"""
    if not prepared:
        return 0
    now = _now()
    field_cols = [f.column for f in spec.fields]
    tuples = []
    for p in prepared:
        tuples.append((
            p["id"],
            *[p["values"].get(c) for c in field_cols],
            p["created_at"],
            now,
            p["raw_json"],
            p["source_hash"],
            None,  # deleted_at: registro visto agora esta vivo
        ))
    with conn.cursor() as cur:
        execute_values(cur, build_upsert_sql(spec), tuples)
    return len(tuples)


def record_history(conn, run_id: str, spec: EntitySpec,
                   events: list[tuple[str, str, str | None, str | None, str | None]]) -> int:
    """events: [(entity_id, op, field, old, new)]"""
    if not events:
        return 0
    rows = [(run_id, spec.name, eid, op, f, old, new)
            for eid, op, f, old, new in events]
    with conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO bling_change_history"
            " (run_id, entity, entity_id, op, field, old_value, new_value) VALUES %s",
            rows,
        )
    return len(rows)


# ---------------------------------------------------------------------------
# Carga de uma entidade
# ---------------------------------------------------------------------------

def load_entity(
    bling: BlingClient,
    conn,
    spec: EntitySpec,
    *,
    mode: Literal["incremental", "full"] = "full",
    max_pages: int = 1,
    page_size: int = 100,
    start_page: int = 1,
    run_id: str | None = None,
    extra_params: dict | None = None,
    detail_when_override: str | None = None,
) -> LoadStats:
    run_id = run_id or str(uuid.uuid4())
    stats = LoadStats(entity=spec.name)
    detail_when = detail_when_override or spec.detail_when

    params = dict(spec.list_params)
    if extra_params:
        params.update(extra_params)

    page = start_page
    for page in range(start_page, start_page + max_pages):
        stats.last_page = page
        logger.info("[%s] Buscando pagina %s...", spec.name, page)
        try:
            items = fetch_page(bling, spec.endpoint, page, page_size, params)
        except DailyQuotaExceeded as exc:
            logger.warning(
                "[%s] %s. Parando na pagina %s (inseridos=%s atualizados=%s). "
                "Reexecute para continuar.",
                spec.name, exc, page, stats.inserted, stats.updated,
            )
            stats.status = "quota"
            return stats

        if not items:
            logger.info("[%s] Sem mais registros na pagina %s.", spec.name, page)
            stats.completed = True
            break

        stats.pages += 1
        stats.fetched += len(items)

        # dedup por id dentro da pagina (paridade com o _dedup antigo)
        seen: dict = {}
        for item in items:
            seen[_item_id(spec, item)] = item
        items = list(seen.values())
        stats.seen_ids.update(i for i in seen if i is not None)

        try:
            processed = _process_page(
                bling, conn, spec, items, run_id, detail_when, stats)
        except DailyQuotaExceeded as exc:
            conn.commit()  # preserva o que ja foi gravado nesta pagina
            logger.warning(
                "[%s] %s durante detalhes na pagina %s; parando.",
                spec.name, exc, page)
            stats.status = "quota"
            return stats

        conn.commit()
        logger.info(
            "[%s]   -> novos=%s alterados=%s inalterados=%s (historico=%s)",
            spec.name, processed["inserted"], processed["updated"],
            processed["unchanged"], processed["history"],
        )
        if len(items) < page_size and not spec.singleton:
            logger.info("[%s] Ultima pagina atingida.", spec.name)
            stats.completed = True
            break
    else:
        # esgotou max_pages sem chegar na ultima pagina
        stats.status = "partial"

    if spec.singleton:
        stats.completed = True
    return stats


def _process_page(bling, conn, spec: EntitySpec, items: list[dict],
                  run_id: str, detail_when: str, stats: LoadStats) -> dict:
    hashes = {_item_id(spec, item): compute_source_hash(item) for item in items}
    existing = select_existing(conn, spec, [i for i in hashes if i is not None])

    new_items, changed_items = [], []
    for item in items:
        item_id = _item_id(spec, item)
        if item_id is None:
            continue
        old = existing.get(item_id)
        if old is None:
            new_items.append(item)
        elif old.get("source_hash") != hashes[item_id]:
            changed_items.append(item)
        else:
            stats.unchanged += 1

    prepared: list[dict] = []
    events: list[tuple] = []

    def resolve(item: dict) -> dict:
        """Item da listagem -> payload completo (detalhe quando configurado)."""
        if spec.detail_endpoint and detail_when in ("changed", "always"):
            detail = fetch_detail(bling, spec, _item_id(spec, item))
            stats.detail_requests += 1
            return detail if detail else item
        return item

    if detail_when == "always":
        # inalterados tambem sao re-buscados (usado no full sweep semanal)
        for item in items:
            item_id = _item_id(spec, item)
            if item_id is None or item in new_items or item in changed_items:
                continue
            changed_items.append(item)
            stats.unchanged -= 1

    for item in new_items:
        payload = resolve(item)
        item_id = _item_id(spec, item)
        values = spec.extract_row(payload)
        created_at = (spec.created_at_field.extract(payload)
                      if spec.created_at_field else _now())
        prepared.append({
            "id": item_id, "values": values, "created_at": created_at,
            "raw_json": json.dumps(payload, ensure_ascii=False),
            "source_hash": hashes[item_id],
        })
        events.append((str(item_id), "I", None, None, None))
        stats.inserted += 1

    for item in changed_items:
        payload = resolve(item)
        item_id = _item_id(spec, item)
        values = spec.extract_row(payload)
        old = existing[item_id]
        changes = diff_row(spec, old, values)
        if old.get("deleted_at") is not None:
            events.append((str(item_id), "R", None, None, None))  # reapareceu
        for column, old_c, new_c in changes:
            events.append((str(item_id), "U", column, old_c, new_c))
        if not changes and old.get("deleted_at") is None:
            # hash de listagem mudou mas nenhuma coluna auditada: so atualiza raw
            stats.unchanged += 1
        else:
            stats.updated += 1
        created_at = (spec.created_at_field.extract(payload)
                      if spec.created_at_field else None)
        prepared.append({
            "id": item_id, "values": values,
            "created_at": created_at or _now(),  # ignorado no conflito (so INSERT)
            "raw_json": json.dumps(payload, ensure_ascii=False),
            "source_hash": hashes[item_id],
        })

    history = record_history(conn, run_id, spec, events)
    stats.history_rows += history
    upsert_rows(conn, spec, prepared)
    return {
        "inserted": len(new_items),
        "updated": len(changed_items),
        "unchanged": len(items) - len(new_items) - len(changed_items),
        "history": history,
    }


# ---------------------------------------------------------------------------
# Carga por lotes de ids (ex.: estoques/saldos exige idsProdutos[])
# ---------------------------------------------------------------------------

def load_id_batched(
    bling: BlingClient,
    conn,
    spec: EntitySpec,
    *,
    run_id: str | None = None,
) -> LoadStats:
    """Itera ids vindos do proprio banco (spec.id_batch_source) em lotes,
    passando-os como parametro repetido (spec.id_batch_param)."""
    run_id = run_id or str(uuid.uuid4())
    stats = LoadStats(entity=spec.name)

    with conn.cursor() as cur:
        cur.execute(spec.id_batch_source)
        ids = [row[0] for row in cur.fetchall()]
    logger.info("[%s] %s ids no banco para consultar em lotes de %s.",
                spec.name, len(ids), spec.id_batch_size)

    for offset in range(0, len(ids), spec.id_batch_size):
        chunk = ids[offset:offset + spec.id_batch_size]
        params = {spec.id_batch_param: chunk, **spec.list_params}
        try:
            items = fetch_page(bling, spec.endpoint, 1, spec.id_batch_size, params)
            stats.pages += 1
            stats.fetched += len(items)
            seen: dict = {}
            for item in items:
                seen[_item_id(spec, item)] = item
            items = list(seen.values())
            stats.seen_ids.update(i for i in seen if i is not None)
            _process_page(bling, conn, spec, items, run_id, "never", stats)
        except DailyQuotaExceeded as exc:
            conn.commit()
            logger.warning("[%s] %s. Parando no lote %s/%s.",
                           spec.name, exc, offset // spec.id_batch_size + 1,
                           -(-len(ids) // spec.id_batch_size))
            stats.status = "quota"
            return stats
        conn.commit()

    stats.completed = True
    return stats


# ---------------------------------------------------------------------------
# Delecao (usado apenas por full sweep completo — Fase 2/3)
# ---------------------------------------------------------------------------

def mark_deleted(conn, spec: EntitySpec, seen_ids: set, run_id: str) -> int:
    """Marca deleted_at nos ids que sumiram da API. So chamar apos full sweep
    completo (todas as paginas percorridas sem erro)."""
    if spec.conflict_columns != ("id",):
        raise NotImplementedError
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id FROM {spec.table} WHERE deleted_at IS NULL", ())
        db_ids = {row[0] for row in cur.fetchall()}
    gone = db_ids - seen_ids
    if not gone:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {spec.table} SET deleted_at = now() WHERE id = ANY(%s)",
            (list(gone),))
    record_history(conn, run_id, spec,
                   [(str(g), "D", None, None, None) for g in gone])
    logger.info("[%s] %s registros marcados como deletados.", spec.name, len(gone))
    return len(gone)
