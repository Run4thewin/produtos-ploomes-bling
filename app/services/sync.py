import logging

from app.clients.bling import BlingClient
from app.clients.ploomes import PloomesClient
from app.config import Settings, get_settings
from app.services.mapping import ProductMappingError, diff_fields, map_bling_to_ploomes

logger = logging.getLogger(__name__)


class ProductSyncService:
    def __init__(
        self,
        settings: Settings | None = None,
        bling: BlingClient | None = None,
        ploomes: PloomesClient | None = None,
    ):
        self.settings = settings or get_settings()
        self.bling = bling or BlingClient(self.settings)
        self.ploomes = ploomes or PloomesClient(self.settings)

    def upsert_from_bling_id(self, product_id: int | str, action: str = "updated") -> dict:
        if action == "deleted":
            return self._suspend_by_bling_id(product_id)

        bling_product = self.bling.get_product(product_id)
        return self.upsert_from_bling_product(bling_product)

    def upsert_from_bling_product(self, bling_product: dict) -> dict:
        try:
            payload = map_bling_to_ploomes(bling_product, self.settings)
        except ProductMappingError as exc:
            code = (bling_product.get("codigo") or "").strip()
            logger.warning("Produto ignorado: %s", exc)
            return {
                "action": "skipped",
                "code": code or None,
                "reason": str(exc),
                "bling_id": bling_product.get("id"),
            }

        code = payload["Code"]
        existing = self.ploomes.get_product_by_code(code)

        if existing:
            result = self.ploomes.update_product(existing["Id"], payload)
            logger.info("Produto atualizado no Ploomes: %s (Id=%s)", code, existing["Id"])
            return {"action": "updated", "code": code, "ploomes_id": existing["Id"], "result": result}

        result = self.ploomes.create_product(payload)
        logger.info("Produto criado no Ploomes: %s | %s", code, payload["Name"])
        return {"action": "created", "code": code, "result": result}

    def _suspend_by_bling_id(self, product_id: int | str) -> dict:
        bling_product = self.bling.get_product(product_id)
        code = (bling_product.get("codigo") or "").strip()
        if not code:
            return {"action": "skipped", "reason": "produto sem codigo", "bling_id": product_id}

        existing = self.ploomes.get_product_by_code(code)
        if not existing:
            return {"action": "skipped", "reason": "nao encontrado no Ploomes", "code": code}

        result = self.ploomes.update_product(existing["Id"], {"Suspended": True})
        logger.info("Produto inativado no Ploomes: %s", code)
        return {"action": "suspended", "code": code, "ploomes_id": existing["Id"], "result": result}

    def full_sync(self) -> dict:
        stats = {"created": 0, "updated": 0, "errors": 0, "skipped": 0}
        for summary in self.bling.iter_products(self.settings.reconcile_page_size):
            try:
                product = self.bling.get_product(summary["id"])
                result = self.upsert_from_bling_product(product)
                stats[result["action"]] = stats.get(result["action"], 0) + 1
            except Exception as exc:
                stats["errors"] += 1
                logger.exception("Erro no full-sync do produto %s: %s", summary.get("id"), exc)
        return stats

    def reconcile(self, apply_fixes: bool = True) -> dict:
        ploomes_by_code: dict[str, dict] = {}
        for product in self.ploomes.iter_products(self.settings.reconcile_page_size):
            code = (product.get("Code") or "").strip()
            if code:
                ploomes_by_code[code] = product

        report = {
            "missing_in_ploomes": [],
            "divergent": [],
            "ok": 0,
            "fixed": 0,
            "errors": 0,
        }

        seen_codes: set[str] = set()
        for summary in self.bling.iter_products(self.settings.reconcile_page_size):
            try:
                bling_product = self.bling.get_product(summary["id"])
                code = (bling_product.get("codigo") or "").strip()
                if not code:
                    continue
                seen_codes.add(code)

                ploomes_product = ploomes_by_code.get(code)
                if not ploomes_product:
                    report["missing_in_ploomes"].append(code)
                    if apply_fixes:
                        self.upsert_from_bling_product(bling_product)
                        report["fixed"] += 1
                    continue

                divergences = diff_fields(bling_product, ploomes_product, self.settings)
                if divergences:
                    report["divergent"].append({"code": code, "fields": divergences})
                    if apply_fixes:
                        self.upsert_from_bling_product(bling_product)
                        report["fixed"] += 1
                else:
                    report["ok"] += 1
            except Exception as exc:
                report["errors"] += 1
                logger.exception("Erro na reconciliacao do produto %s: %s", summary.get("id"), exc)

        report["orphan_in_ploomes"] = [
            code for code in ploomes_by_code if code not in seen_codes
        ]
        return report
