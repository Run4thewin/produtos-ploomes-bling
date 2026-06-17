from typing import Any


PLOOMES_ACTIONS = {
    1: "create",
    2: "update",
    3: "delete",
}


def parse_ploomes_webhook(payload: dict[str, Any], product_entity_id: int) -> dict[str, Any]:
    entity_id = payload.get("EntityId")
    if entity_id is not None and entity_id != product_entity_id:
        return {"status": "ignored", "reason": "entity_nao_produto"}

    action_id = payload.get("ActionId")
    action = PLOOMES_ACTIONS.get(action_id, "update")

    product = payload.get("New") or payload.get("Old") or payload
    product_id = (
        product.get("Id")
        or payload.get("Id")
        or payload.get("ProductId")
        or payload.get("ObjectId")
    )

    if not product_id:
        return {"status": "ignored", "reason": "sem_product_id"}

    return {
        "status": "accepted",
        "product_id": str(product_id),
        "action": action,
        "entity_id": entity_id,
        "action_id": action_id,
    }


def parse_ploomes_deal_webhook(payload: dict[str, Any], deal_entity_id: int) -> dict[str, Any]:
    entity_id = payload.get("EntityId")
    if deal_entity_id and entity_id is not None and entity_id != deal_entity_id:
        return {"status": "ignored", "reason": "entity_nao_deal"}

    action_id = payload.get("ActionId")
    action = PLOOMES_ACTIONS.get(action_id, "update")

    deal = payload.get("New") or payload.get("Old") or payload
    deal_id = (
        deal.get("Id")
        or payload.get("Id")
        or payload.get("DealId")
        or payload.get("ObjectId")
    )

    if not deal_id:
        return {"status": "ignored", "reason": "sem_deal_id"}

    return {
        "status": "accepted",
        "deal_id": str(deal_id),
        "action": action,
        "entity_id": entity_id,
        "action_id": action_id,
    }
