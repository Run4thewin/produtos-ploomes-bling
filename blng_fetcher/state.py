"""
blng_fetcher/state.py
Persistencia do estado de sincronizacao por entidade (tabela bling_sync_state):
watermark incremental, retomada por pagina apos quota e controle de full sweep.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

ADVISORY_LOCK_KEY = "blng_fetcher"


@dataclass
class SyncState:
    entity: str
    watermark: datetime | None = None
    last_run_at: datetime | None = None
    last_run_id: str | None = None
    last_status: str | None = None
    last_page: int | None = None
    last_full_sweep_at: datetime | None = None
    details: dict | None = None


def acquire_lock(conn) -> bool:
    """Advisory lock p/ evitar execucoes horarias sobrepostas."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (ADVISORY_LOCK_KEY,))
        return bool(cur.fetchone()[0])


def release_lock(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (ADVISORY_LOCK_KEY,))


def get_state(conn, entity: str) -> SyncState:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT entity, watermark, last_run_at, last_run_id, last_status,"
            " last_page, last_full_sweep_at, details"
            " FROM bling_sync_state WHERE entity = %s",
            (entity,),
        )
        row = cur.fetchone()
    if not row:
        return SyncState(entity=entity)
    return SyncState(
        entity=row[0], watermark=row[1], last_run_at=row[2],
        last_run_id=str(row[3]) if row[3] else None, last_status=row[4],
        last_page=row[5], last_full_sweep_at=row[6], details=row[7],
    )


def save_state(conn, state: SyncState) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bling_sync_state
                (entity, watermark, last_run_at, last_run_id, last_status,
                 last_page, last_full_sweep_at, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (entity) DO UPDATE SET
                watermark          = EXCLUDED.watermark,
                last_run_at        = EXCLUDED.last_run_at,
                last_run_id        = EXCLUDED.last_run_id,
                last_status        = EXCLUDED.last_status,
                last_page          = EXCLUDED.last_page,
                last_full_sweep_at = EXCLUDED.last_full_sweep_at,
                details            = EXCLUDED.details
            """,
            (
                state.entity, state.watermark, state.last_run_at,
                state.last_run_id, state.last_status, state.last_page,
                state.last_full_sweep_at,
                json.dumps(state.details, ensure_ascii=False, default=str)
                if state.details is not None else None,
            ),
        )
    conn.commit()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def due_for_full_sweep(state: SyncState, full_sweep_days: int) -> bool:
    if state.last_full_sweep_at is None:
        return True
    return now_utc() - state.last_full_sweep_at > timedelta(days=full_sweep_days)


def due_for_refresh(state: SyncState, refresh_hours: int) -> bool:
    """small_config: so recarrega a cada refresh_hours."""
    if state.last_run_at is None or state.last_status != "ok":
        return True
    return now_utc() - state.last_run_at >= timedelta(hours=refresh_hours)
