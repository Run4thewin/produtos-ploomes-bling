import logging

from app.clients.bling import BlingClient
from app.clients.ploomes import PloomesClient
from app.config import Settings, get_settings
from app.services.mapping import ProductMappingError, map_ploomes_to_bling

logger = logging.getLogger(__name__)


class PloomesToBlingSyncService:
    def __init__(
        self,
        settings: Settings | None = None,
        bling: BlingClient | None = None,
        ploomes: PloomesClient | None = None,
    ):
        self.settings = settings or get_settings()
        self.bling = bling or BlingClient(self.settings)
        self.ploomes = ploomes or PloomesClient(self.settings)

    def upsert_from_ploomes_id(self, product_id: int | str, action: str = "create") -> dict:
        if action == "delete":
            return {"action": "skipped", "reason": "exclusao no Bling nao automatizada"}

        ploomes_product = self.ploomes.get_product_by_id(product_id)
        return self.upsert_from_ploomes_product(ploomes_product, action=action)

    def upsert_from_ploomes_product(
        self,
        ploomes_product: dict,
        action: str = "create",
    ) -> dict:
        try:
            payload = map_ploomes_to_bling(ploomes_product, self.settings)
        except ProductMappingError as exc:
            logger.warning("Produto Ploomes ignorado: %s", exc)
            return {
                "action": "skipped",
                "ploomes_id": ploomes_product.get("Id"),
                "reason": str(exc),
            }

        code = payload["codigo"]
        existing = self.bling.get_product_by_code(code)

        if existing:
            if action == "create":
                logger.info("Produto ja existe no Bling: %s (Id=%s)", code, existing.get("id"))
                return {
                    "action": "exists",
                    "code": code,
                    "bling_id": existing.get("id"),
                }

            result = self.bling.update_product(existing["id"], payload)
            logger.info("Produto atualizado no Bling: %s (Id=%s)", code, existing["id"])
            return {
                "action": "updated",
                "code": code,
                "bling_id": existing["id"],
                "result": result,
            }

        result = self.bling.create_product(payload)
        bling_id = result.get("id") if isinstance(result, dict) else None
        logger.info("Produto criado no Bling: %s | %s", code, payload["nome"])
        return {
            "action": "created",
            "code": code,
            "bling_id": bling_id,
            "result": result,
        }
