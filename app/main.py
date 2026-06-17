import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel

from app.clients.bling import BlingClient
from app.config import get_settings
from app.logging_config import setup_logging
from app.services.ploomes_webhook import parse_ploomes_deal_webhook, parse_ploomes_webhook
from app.services.queue import ProductEventQueue
from app.services.sync_deal_to_bling_order import DealToBlingOrderSyncService
from app.services.sync import ProductSyncService
from app.services.sync_ploomes_to_bling import PloomesToBlingSyncService
from app.services.webhook import verify_bling_signature

setup_logging()
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


@app.get("/bling/contatos", tags=["Bling"])
def search_bling_contacts(
    pesquisa: str | None = Query(
        default=None,
        description="Opcional. Nome, e-mail, codigo ou termo geral. Sem filtros, lista todos paginados.",
    ),
    numero_documento: str | None = Query(
        default=None,
        description="Opcional. CPF ou CNPJ do contato.",
    ),
    telefone: str | None = Query(default=None, description="Opcional. Telefone do contato."),
    uf: str | None = Query(default=None, description="Opcional. UF do contato."),
    criterio: int | None = Query(
        default=None,
        description="Opcional. 1=ultimos incluidos, 2=ativos, 3=inativos, 4=excluidos, 5=todos",
    ),
    tipo_pessoa: int | None = Query(
        default=None,
        description="Opcional. 1=fisica, 2=juridica, 3=estrangeiro",
    ),
    pagina: int = Query(default=1, ge=1, description="Numero da pagina"),
    limite: int = Query(default=20, ge=1, le=100, description="Registros por pagina"),
) -> dict[str, Any]:
    """Lista ou busca contatos cadastrados no Bling. Sem filtros, retorna a listagem geral paginada."""
    try:
        bling = BlingClient(get_settings())
        result = bling.search_contacts(
            pesquisa=pesquisa,
            numero_documento=numero_documento,
            telefone=telefone,
            uf=uf,
            criterio=criterio,
            tipo_pessoa=tipo_pessoa,
            pagina=pagina,
            limite=limite,
        )
        contacts = result.get("data", [])
        return {
            "total_pagina": len(contacts),
            "pagina": pagina,
            "limite": limite,
            "filtros": {
                k: v
                for k, v in {
                    "pesquisa": pesquisa,
                    "numero_documento": numero_documento,
                    "telefone": telefone,
                    "uf": uf,
                    "criterio": criterio,
                    "tipo_pessoa": tipo_pessoa,
                }.items()
                if v is not None
            },
            "contatos": contacts,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erro ao buscar contatos no Bling")
        raise HTTPException(status_code=502, detail=f"Erro ao buscar contatos: {exc}") from exc


@app.get("/bling/empresas-com-contatos", tags=["Bling"])
def list_bling_companies_with_contacts(
    pagina: int = Query(default=1, ge=1, description="Numero da pagina"),
    limite: int = Query(default=20, ge=1, le=100, description="Registros por pagina"),
    apenas_com_vinculos: bool = Query(
        default=False,
        description="Se true, retorna apenas empresas com pessoasContato preenchido",
    ),
) -> dict[str, Any]:
    """Lista empresas PJ do Bling com pessoasContato agregadas."""
    try:
        bling = BlingClient(get_settings())
        return bling.list_companies_with_contacts(
            pagina=pagina,
            limite=limite,
            apenas_com_vinculos=apenas_com_vinculos,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erro ao listar empresas com contatos no Bling")
        raise HTTPException(status_code=502, detail=f"Erro ao listar empresas: {exc}") from exc


@app.get("/bling/contatos/{contact_id}", tags=["Bling"])
def get_bling_contact(contact_id: int) -> dict[str, Any]:
    """Retorna um contato do Bling pelo ID, incluindo pessoasContato quando for empresa."""
    try:
        bling = BlingClient(get_settings())
        return bling.get_contact(contact_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erro ao buscar contato %s no Bling", contact_id)
        raise HTTPException(status_code=502, detail=f"Erro ao buscar contato: {exc}") from exc


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


@app.post("/webhooks/ploomes/deals")
async def ploomes_deal_webhook(
    request: Request,
    validation_key: str | None = Query(default=None),
) -> dict[str, Any]:
    settings = get_settings()
    _check_ploomes_validation_key(validation_key)

    payload: dict[str, Any] = await request.json()
    parsed = parse_ploomes_deal_webhook(payload, settings.ploomes_deal_entity_id)

    if parsed.get("status") != "accepted":
        logger.info("Webhook Ploomes Deal ignorado: %s", parsed)
        return parsed

    if parsed["action"] == "delete":
        return {"status": "ignored", "reason": "delete_nao_processado"}

    try:
        result = DealToBlingOrderSyncService(settings).create_bling_order_from_deal(
            parsed["deal_id"]
        )
        return {"status": "processed", "deal_id": parsed["deal_id"], "result": result}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erro ao processar Deal %s via webhook", parsed["deal_id"])
        raise HTTPException(status_code=502, detail=f"Erro ao processar Deal: {exc}") from exc


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
    limit: int | None = Query(
        default=None,
        ge=1,
        description="Opcional. Limita a quantidade de produtos (ex: 5 para teste piloto).",
    ),
) -> dict[str, Any]:
    _check_internal_secret(x_internal_secret)
    try:
        result = ProductSyncService().full_sync(limit=limit)
        return {"status": "completed", **result}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/jobs/reconcile")
def reconcile_job(
    x_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_internal_secret(x_internal_secret)
    report = ProductSyncService().reconcile(apply_fixes=True)
    return {"status": "completed", "report": report}
