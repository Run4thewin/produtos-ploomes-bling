"""
blng_fetcher/main.py
Busca entidades do Bling e faz upsert no PostgreSQL, com historico de
mudancas (bling_change_history) e carga incremental (bling_sync_state).

Uso:
    python -m blng_fetcher.main --entity all --mode incremental --pages 999  # producao
    python -m blng_fetcher.main --entity contacts --mode full --pages 5      # backfill
    python -m blng_fetcher.main --entity nfe-detail                          # backfill NF-e

Entidades: all | config | transacional | <nome da spec> | nfe-detail
(specs em blng_fetcher/specs; requer scripts/sql/001 e 002 aplicados)
"""
import argparse
import json
import logging
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from app.clients.bling import BlingClient  # noqa: E402
from app.clients.rate_limit import DailyQuotaExceeded  # noqa: E402

from blng_fetcher import engine  # noqa: E402
from blng_fetcher import state as sync_state  # noqa: E402
from blng_fetcher.specs import GROUPS, SPECS  # noqa: E402
from blng_fetcher.specs.base import EntitySpec, _parse_date  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

FULL_SWEEP_DAYS = int(os.environ.get("BLING_FULL_SWEEP_DAYS", "7"))


def get_db_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


# ---------------------------------------------------------------------------
# Validacao de schema (DDL e' manual; ver scripts/sql/)
# ---------------------------------------------------------------------------

def _table_exists(conn, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table,))
        return cur.fetchone()[0] is not None


def _column_exists(conn, table: str, column: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns"
            " WHERE table_name = %s AND column_name = %s",
            (table, column),
        )
        return cur.fetchone() is not None


def check_infra(conn) -> bool:
    missing = [t for t in ("bling_change_history", "bling_sync_state")
               if not _table_exists(conn, t)]
    if missing:
        logger.error(
            "Tabelas de infraestrutura ausentes: %s. "
            "Rode scripts/sql/001_bling_infra.sql como postgres.", missing)
        return False
    return True


def check_entity_table(conn, spec: EntitySpec) -> bool:
    if not _table_exists(conn, spec.table):
        logger.warning(
            "[%s] Tabela %s nao existe; pulando. "
            "Rode o CREATE TABLE correspondente (scripts/sql/).",
            spec.name, spec.table)
        return False
    if not _column_exists(conn, spec.table, "source_hash"):
        logger.warning(
            "[%s] Tabela %s sem coluna source_hash; pulando. "
            "Rode scripts/sql/002_bling_alter_core.sql (ou o 003) como postgres.",
            spec.name, spec.table)
        return False
    return True


# ---------------------------------------------------------------------------
# Orquestracao de uma entidade
# ---------------------------------------------------------------------------

def run_entity(bling: BlingClient, conn, spec: EntitySpec, *,
               mode: str, max_pages: int, page_size: int, start_page: int,
               explicit: bool) -> engine.LoadStats | None:
    """explicit=True quando o usuario pediu essa entidade pelo nome
    (ignora o cooldown de small_config)."""
    st = sync_state.get_state(conn, spec.name)
    run_id = str(uuid.uuid4())
    run_started = sync_state.now_utc()

    if (spec.refresh_hours > 1 and not explicit
            and not sync_state.due_for_refresh(st, spec.refresh_hours)):
        logger.info("[%s] em cooldown (%sh); pulando.",
                    spec.name, spec.refresh_hours)
        return None

    extra_params: dict = {}
    effective_mode = mode
    is_full_sweep = False
    resume_page = start_page

    resuming = (st.last_status == "quota" and st.last_page
                and start_page == 1)
    if resuming:
        resume_page = st.last_page
        saved = st.details or {}
        extra_params = saved.get("params") or {}
        effective_mode = saved.get("mode") or mode
        is_full_sweep = bool(saved.get("full_sweep"))
        logger.info("[%s] Retomando da pagina %s (quota anterior).",
                    spec.name, resume_page)
    elif mode == "incremental":
        if not spec.small_config and sync_state.due_for_full_sweep(st, FULL_SWEEP_DAYS):
            is_full_sweep = True
            logger.info("[%s] Full sweep periodico (ultimo: %s).",
                        spec.name, st.last_full_sweep_at)
        elif spec.incremental_param and st.watermark:
            # a sondagem provou que os filtros do Bling so ativam em PAR
            # Inicial+Final; o Final vai um dia a frente p/ nao cortar o agora
            since = st.watermark - timedelta(minutes=spec.watermark_overlap_minutes)
            until = run_started + timedelta(days=1)
            extra_params[spec.incremental_param] = since.strftime("%Y-%m-%d")
            final = (spec.incremental_param_final
                     or spec.incremental_param.replace("Inicial", "Final"))
            extra_params[final] = until.strftime("%Y-%m-%d")
        elif spec.window_param:
            since = run_started - timedelta(days=spec.window_days_back)
            until = run_started + timedelta(days=spec.window_days_back)
            extra_params[spec.window_param] = since.strftime("%Y-%m-%d")
            final = (spec.window_param_final
                     or spec.window_param.replace("Inicial", "Final"))
            extra_params[final] = until.strftime("%Y-%m-%d")
        # sem suporte incremental: full (barato p/ small_config; inevitavel p/ resto)
    else:
        is_full_sweep = True  # mode=full explicito

    detail_override = None
    if is_full_sweep and spec.detail_endpoint:
        detail_override = "always"  # corrige deriva de campos so-do-detalhe

    if spec.id_batch_source:
        stats = engine.load_id_batched(bling, conn, spec, run_id=run_id)
    else:
        stats = engine.load_entity(
            bling, conn, spec,
            mode=effective_mode, max_pages=max_pages, page_size=page_size,
            start_page=resume_page, run_id=run_id, extra_params=extra_params,
            detail_when_override=detail_override,
        )

    # ------- persistencia do estado -------
    st.last_run_at = run_started
    st.last_run_id = run_id
    st.last_status = stats.status
    st.last_page = stats.last_page if stats.status == "quota" else None
    st.details = {
        "params": extra_params, "mode": effective_mode,
        "full_sweep": is_full_sweep,
        "fetched": stats.fetched, "inserted": stats.inserted,
        "updated": stats.updated, "unchanged": stats.unchanged,
        "history_rows": stats.history_rows,
        "detail_requests": stats.detail_requests,
    }

    if stats.completed and stats.status == "ok":
        # watermark so avanca quando a varredura garantiu ver tudo o que mudou
        # desde o watermark anterior: varredura completa sem filtro, ou
        # incremental filtrada por dataAlteracao.
        used_incremental_filter = bool(
            spec.incremental_param and spec.incremental_param in extra_params)
        if (is_full_sweep and not extra_params) or used_incremental_filter:
            st.watermark = run_started
        if is_full_sweep and not extra_params:
            st.last_full_sweep_at = run_started
            # delecao so e' confiavel se a varredura cobriu DESDE a pagina 1
            # (retomada/start-page>1 nao viu os ids das paginas anteriores)
            if resume_page == 1:
                engine.mark_deleted(conn, spec, stats.seen_ids, run_id)
                conn.commit()

    sync_state.save_state(conn, st)
    logger.info(
        "[%s] Carga concluida: status=%s novos=%s alterados=%s inalterados=%s "
        "historico=%s detalhes=%s",
        spec.name, stats.status, stats.inserted, stats.updated,
        stats.unchanged, stats.history_rows, stats.detail_requests,
    )
    return stats


# ---------------------------------------------------------------------------
# Backfill: busca detalhe /nfe/{id} para cada registro ja no banco (legado)
# ---------------------------------------------------------------------------

def _load_nfe_details(bling: BlingClient, conn, batch_size: int = 50) -> int:
    spec = SPECS["nfe"]
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
            detail = engine.fetch_detail(bling, spec, nfe_id)
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

        values = spec.extract_row(detail)
        set_clause = ", ".join(f"{c} = %s" for c in values)
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE bling_nfe SET {set_clause}, updated_at = now(),"
                f" raw_json = %s WHERE id = %s",
                (*values.values(), json.dumps(detail, ensure_ascii=False), nfe_id),
            )
        updated += 1

        if i % batch_size == 0:
            conn.commit()
            logger.info("[nfe-detail] %s/%s processadas...", i, total)

    conn.commit()
    logger.info("[nfe-detail] Concluido. %s notas atualizadas.", updated)
    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def resolve_targets(entity: str) -> list[EntitySpec]:
    if entity in GROUPS:
        return [SPECS[name] for name in GROUPS[entity]]
    if entity in SPECS:
        spec = SPECS[entity]
        if not spec.enabled:
            logger.warning(
                "[%s] Spec desabilitada (sem escopo OAuth?); rodando mesmo assim "
                "por pedido explicito.", entity)
        return [spec]
    raise SystemExit(f"Entidade desconhecida: {entity}. "
                     f"Opcoes: {', '.join(sorted(SPECS))} | {', '.join(GROUPS)}")


def main(entity: str = "all", mode: str = "incremental", max_pages: int = 1,
         page_size: int = 100, start_page: int = 1):
    logger.info(
        "Iniciando carga — entity=%s mode=%s max_pages=%s page_size=%s start_page=%s",
        entity, mode, max_pages, page_size, start_page,
    )

    bling = BlingClient()
    conn = get_db_conn()
    logger.info("Conectado ao banco %s@%s", os.environ["DB_NAME"], os.environ["DB_HOST"])

    try:
        if not sync_state.acquire_lock(conn):
            logger.warning("Outra execucao do blng_fetcher em andamento; saindo.")
            return
        if not check_infra(conn):
            return

        if entity == "nfe-detail":
            _load_nfe_details(bling, conn)
            return

        explicit = entity not in GROUPS
        for spec in resolve_targets(entity):
            if not check_entity_table(conn, spec):
                continue
            try:
                run_entity(
                    bling, conn, spec,
                    mode=mode, max_pages=max_pages, page_size=page_size,
                    start_page=start_page, explicit=explicit,
                )
            except DailyQuotaExceeded as exc:
                logger.warning("Quota diaria atingida (%s); parando tudo.", exc)
                break
            except Exception:
                logger.exception("[%s] Falha na carga; seguindo para a proxima.",
                                 spec.name)
                conn.rollback()
    finally:
        try:
            sync_state.release_lock(conn)
        except Exception:  # noqa: BLE001
            pass
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Bling entities to PostgreSQL")
    parser.add_argument(
        "--entity", default="all",
        help="all | config | transacional | nfe-detail | nome da spec "
             f"({', '.join(sorted(SPECS))})",
    )
    parser.add_argument(
        "--mode", default="incremental", choices=["incremental", "full"],
        help="incremental usa watermark/janela; full varre tudo (backfill)",
    )
    parser.add_argument("--pages", type=int, default=1, help="Max de paginas (default: 1)")
    parser.add_argument("--page-size", type=int, default=100,
                        help="Registros por pagina (default: 100)")
    parser.add_argument(
        "--start-page", type=int, default=1,
        help="Pagina inicial (default: 1). Use para retomar uma carga interrompida.",
    )
    args = parser.parse_args()
    main(entity=args.entity, mode=args.mode, max_pages=args.pages,
         page_size=args.page_size, start_page=args.start_page)
