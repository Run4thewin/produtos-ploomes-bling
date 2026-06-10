import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import get_settings
from app.services.ploomes_webhook import parse_ploomes_webhook
from app.services.queue import ProductEventQueue
from app.services.sync import ProductSyncService
from app.services.sync_ploomes_to_bling import PloomesToBlingSyncService
from app.services.webhook import verify_bling_signature

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Ploomes Bling Products Sync",
    description="Sincroniza produtos entre Bling e Ploomes via webhooks.",
    version="1.1.0",
)


class ProcessBlingProductPayload(BaseModel):
    product_id: str
    action: str = "updated"
    event_id: str | None = None


class ProcessPloomesProductPayload(BaseModel):
    product_id: str
    action: str = "create"


def _check_internal_secret(secret: str | None) -> None:
    settings = get_settings()
    if not settings.internal_secret:
        raise HTTPException(status_code=500, detail="INTERNAL_SECRET nao configurado")
    if secret != settings.internal_secret:
        raise HTTPException(status_code=401, detail="Nao autorizado")


def _check_ploomes_validation_key(validation_key: str | None) -> None:
    settings = get_settings()
    expected = settings.ploomes_webhook_validation_key
    if expected and validation_key != expected:
        raise HTTPException(status_code=401, detail="ValidationKey invalida")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/bling")
async def bling_webhook(
    request: Request,
    x_bling_signature_256: str | None = Header(default=None),
) -> dict[str, str]:
    settings = get_settings()
    raw_body = await request.body()

    if not verify_bling_signature(
        raw_body,
        x_bling_signature_256,
        settings.bling_client_secret,
    ):
        raise HTTPException(status_code=401, detail="Assinatura invalida")

    payload: dict[str, Any] = await request.json()
    action = payload.get("action") or payload.get("$action") or "updated"
    data = payload.get("data") or {}
    product_id = data.get("id")
    event_id = payload.get("eventId")

    if not product_id:
        logger.warning("Webhook Bling sem product id: %s", payload)
        return {"status": "ignored"}

    ProductEventQueue(settings).enqueue_bling(product_id, action, event_id)
    return {"status": "accepted"}


@app.post("/webhooks/ploomes")
async def ploomes_webhook(
    request: Request,
    validation_key: str | None = Query(default=None),
) -> dict[str, Any]:
    settings = get_settings()
    _check_ploomes_validation_key(validation_key)

    payload: dict[str, Any] = await request.json()
    parsed = parse_ploomes_webhook(payload, settings.ploomes_product_entity_id)

    if parsed.get("status") != "accepted":
        logger.info("Webhook Ploomes ignorado: %s", parsed)
        return parsed

    action = parsed["action"]
    if action == "delete":
        return {"status": "ignored", "reason": "delete_nao_processado"}

    ProductEventQueue(settings).enqueue_ploomes(parsed["product_id"], action)
    return {"status": "accepted", "product_id": parsed["product_id"], "action": action}


@app.post("/tasks/process-bling-product")
def process_bling_product_task(
    body: ProcessBlingProductPayload,
    x_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_internal_secret(x_internal_secret)
    result = ProductSyncService().upsert_from_bling_id(body.product_id, body.action)
    return {"status": "processed", "result": result}


@app.post("/tasks/process-ploomes-product")
def process_ploomes_product_task(
    body: ProcessPloomesProductPayload,
    x_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_internal_secret(x_internal_secret)
    result = PloomesToBlingSyncService().upsert_from_ploomes_id(body.product_id, body.action)
    return {"status": "processed", "result": result}


@app.post("/tasks/process-product")
def process_product_task_legacy(
    body: ProcessBlingProductPayload,
    x_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    return process_bling_product_task(body, x_internal_secret)


@app.post("/jobs/full-sync")
def full_sync_job(
    x_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_internal_secret(x_internal_secret)
    stats = ProductSyncService().full_sync()
    return {"status": "completed", "stats": stats}


@app.post("/jobs/reconcile")
def reconcile_job(
    x_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_internal_secret(x_internal_secret)
    report = ProductSyncService().reconcile(apply_fixes=True)
    return {"status": "completed", "report": report}
