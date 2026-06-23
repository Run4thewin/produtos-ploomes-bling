import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx

from app.clients.bling import BlingClient
from app.clients.ploomes import PloomesClient
from app.config import Settings, get_settings
from app.services.mapping import ProductMappingError, diff_fields, map_bling_to_ploomes

logger = logging.getLogger(__name__)

SYNC_PREFIX = "[SYNC]"


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

        try:
            bling_product = self.bling.get_product(product_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning(
                    "%s SKIP bling_id=%s | produto nao encontrado no Bling",
                    SYNC_PREFIX,
                    product_id,
                )
                return {
                    "action": "skipped",
                    "reason": "produto nao encontrado no Bling",
                    "bling_id": product_id,
                }
            raise
        return self.upsert_from_bling_product(bling_product)

    def upsert_from_bling_product(self, bling_product: dict) -> dict:
        bling_id = bling_product.get("id")
        code = (bling_product.get("codigo") or "").strip()
        name = (bling_product.get("descricaoCurta") or bling_product.get("nome") or "").strip()

        try:
            payload = map_bling_to_ploomes(bling_product, self.settings)
        except ProductMappingError as exc:
            logger.warning(
                "%s SKIP bling_id=%s code=%s name=%s | motivo=%s",
                SYNC_PREFIX,
                bling_id,
                code or "-",
                name or "-",
                exc,
            )
            return {
                "action": "skipped",
                "code": code or None,
                "name": name or None,
                "reason": str(exc),
                "bling_id": bling_id,
            }

        code = payload["Code"]
        existing = self.ploomes.get_product_by_code(code)

        if existing:
            result = self.ploomes.update_product(existing["Id"], payload)
            logger.info(
                "%s UPDATE bling_id=%s code=%s ploomes_id=%s | %s",
                SYNC_PREFIX,
                bling_id,
                code,
                existing["Id"],
                payload["Name"],
            )
            return {
                "action": "updated",
                "code": code,
                "name": payload["Name"],
                "bling_id": bling_id,
                "ploomes_id": existing["Id"],
                "result": result,
            }

        result = self.ploomes.create_product(payload)
        ploomes_id = result.get("Id") or result.get("value", {}).get("Id")
        logger.info(
            "%s CREATE bling_id=%s code=%s ploomes_id=%s | %s",
            SYNC_PREFIX,
            bling_id,
            code,
            ploomes_id or "-",
            payload["Name"],
        )
        return {
            "action": "created",
            "code": code,
            "name": payload["Name"],
            "bling_id": bling_id,
            "ploomes_id": ploomes_id,
            "result": result,
        }

    def _suspend_by_bling_id(self, product_id: int | str) -> dict:
        try:
            bling_product = self.bling.get_product(product_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning(
                    "%s SKIP delete bling_id=%s | produto nao encontrado no Bling",
                    SYNC_PREFIX,
                    product_id,
                )
                return {
                    "action": "skipped",
                    "reason": "produto nao encontrado no Bling",
                    "bling_id": product_id,
                }
            raise
        code = (bling_product.get("codigo") or "").strip()
        if not code:
            return {"action": "skipped", "reason": "produto sem codigo", "bling_id": product_id}

        existing = self.ploomes.get_product_by_code(code)
        if not existing:
            return {"action": "skipped", "reason": "nao encontrado no Ploomes", "code": code}

        result = self.ploomes.update_product(existing["Id"], {"Suspended": True})
        logger.info("%s SUSPEND code=%s ploomes_id=%s", SYNC_PREFIX, code, existing["Id"])
        return {"action": "suspended", "code": code, "ploomes_id": existing["Id"], "result": result}

    def full_sync(self, limit: int | None = None) -> dict[str, Any]:
        started = time.monotonic()
        page_size = self.settings.reconcile_page_size
        workers = max(1, self.settings.sync_workers)
        max_products = limit if limit and limit > 0 else None

        logger.info(
            "%s INICIO full-sync | workers=%s page_size=%s limit=%s",
            SYNC_PREFIX,
            workers,
            page_size,
            max_products or "todos",
        )

        stats: dict[str, int] = {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "suspended": 0,
            "errors": 0,
            "total": 0,
        }
        errors_detail: list[dict[str, Any]] = []
        lock = threading.Lock()
        total_before_batch = 0
        page_number = 0

        batch: list[dict] = []
        products_collected = 0
        for summary in self.bling.iter_products(page_size):
            if max_products and products_collected >= max_products:
                break

            batch.append(summary)
            products_collected += 1

            should_process = len(batch) >= page_size or (
                max_products is not None and products_collected >= max_products
            )
            if not should_process:
                continue

            page_number += 1
            self._process_full_sync_batch(
                batch=batch,
                page_number=page_number,
                workers=workers,
                stats=stats,
                errors_detail=errors_detail,
                lock=lock,
                processed_before=total_before_batch,
            )
            total_before_batch += len(batch)
            batch = []

        if batch:
            page_number += 1
            self._process_full_sync_batch(
                batch=batch,
                page_number=page_number,
                workers=workers,
                stats=stats,
                errors_detail=errors_detail,
                lock=lock,
                processed_before=total_before_batch,
            )

        elapsed = round(time.monotonic() - started, 2)
        rate = round(stats["total"] / elapsed, 2) if elapsed > 0 else 0.0

        logger.info(
            "%s FIM full-sync | total=%s created=%s updated=%s skipped=%s errors=%s "
            "elapsed=%ss rate=%s produtos/s",
            SYNC_PREFIX,
            stats["total"],
            stats["created"],
            stats["updated"],
            stats["skipped"],
            stats["errors"],
            elapsed,
            rate,
        )

        if errors_detail:
            logger.warning("%s ERROS (%s):", SYNC_PREFIX, len(errors_detail))
            for item in errors_detail:
                logger.warning(
                    "%s ERRO bling_id=%s code=%s | %s",
                    SYNC_PREFIX,
                    item.get("bling_id"),
                    item.get("code") or "-",
                    item.get("error"),
                )

        return {
            "stats": stats,
            "elapsed_seconds": elapsed,
            "products_per_second": rate,
            "pages_processed": page_number,
            "workers": workers,
            "limit": max_products,
            "errors_detail": errors_detail,
        }

    def _process_full_sync_batch(
        self,
        batch: list[dict],
        page_number: int,
        workers: int,
        stats: dict[str, int],
        errors_detail: list[dict[str, Any]],
        lock: threading.Lock,
        processed_before: int,
    ) -> None:
        batch_size = len(batch)
        logger.info(
            "%s PAGINA %s iniciada | produtos=%s | workers=%s",
            SYNC_PREFIX,
            page_number,
            batch_size,
            workers,
        )
        page_started = time.monotonic()

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self._sync_single_product, summary): summary for summary in batch
            }
            for index, future in enumerate(as_completed(futures), start=1):
                summary = futures[future]
                bling_id = summary.get("id")
                try:
                    result = future.result()
                except Exception as exc:
                    result = {
                        "action": "error",
                        "bling_id": bling_id,
                        "code": None,
                        "error": str(exc),
                    }
                    logger.exception(
                        "%s ERRO bling_id=%s | %s",
                        SYNC_PREFIX,
                        bling_id,
                        exc,
                    )

                with lock:
                    action = result.get("action", "error")
                    if action == "error":
                        stats["errors"] += 1
                        errors_detail.append(
                            {
                                "bling_id": result.get("bling_id", bling_id),
                                "code": result.get("code"),
                                "name": result.get("name"),
                                "error": result.get("error", "erro desconhecido"),
                            }
                        )
                    else:
                        stats[action] = stats.get(action, 0) + 1
                    stats["total"] += 1
                    global_index = processed_before + index

                elapsed_item = result.get("elapsed_seconds")
                if action in {"created", "updated"}:
                    logger.info(
                        "%s OK %s/%s pagina=%s | %s bling_id=%s code=%s%s",
                        SYNC_PREFIX,
                        global_index,
                        "?",
                        page_number,
                        action.upper(),
                        result.get("bling_id", bling_id),
                        result.get("code") or "-",
                        f" elapsed={elapsed_item}s" if elapsed_item else "",
                    )
                elif action == "skipped":
                    logger.warning(
                        "%s SKIP %s/%s pagina=%s | bling_id=%s code=%s | %s",
                        SYNC_PREFIX,
                        global_index,
                        "?",
                        page_number,
                        result.get("bling_id", bling_id),
                        result.get("code") or "-",
                        result.get("reason", "ignorado"),
                    )

                progress_every = self.settings.sync_progress_every
                if progress_every > 0 and global_index % progress_every == 0:
                    with lock:
                        logger.info(
                            "%s PROGRESSO total=%s created=%s updated=%s skipped=%s errors=%s",
                            SYNC_PREFIX,
                            stats["total"],
                            stats["created"],
                            stats["updated"],
                            stats["skipped"],
                            stats["errors"],
                        )

        page_elapsed = round(time.monotonic() - page_started, 2)
        logger.info(
            "%s PAGINA %s concluida | produtos=%s | elapsed=%ss",
            SYNC_PREFIX,
            page_number,
            batch_size,
            page_elapsed,
        )

    def _sync_single_product(self, summary: dict) -> dict:
        started = time.monotonic()
        bling_id = summary.get("id")
        bling = BlingClient(self.settings)
        ploomes = PloomesClient(self.settings)
        service = ProductSyncService(self.settings, bling, ploomes)

        product = bling.get_product(bling_id)
        result = service.upsert_from_bling_product(product)
        result["elapsed_seconds"] = round(time.monotonic() - started, 2)
        return result

    def reconcile(self, apply_fixes: bool = True) -> dict:
        logger.info("%s INICIO reconcile | apply_fixes=%s", SYNC_PREFIX, apply_fixes)
        started = time.monotonic()

        ploomes_by_code: dict[str, dict] = {}
        for product in self.ploomes.iter_products(self.settings.reconcile_page_size):
            code = (product.get("Code") or "").strip()
            if code:
                ploomes_by_code[code] = product

        logger.info("%s reconcile | produtos no Ploomes=%s", SYNC_PREFIX, len(ploomes_by_code))

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
                    logger.warning("%s reconcile MISSING code=%s", SYNC_PREFIX, code)
                    if apply_fixes:
                        self.upsert_from_bling_product(bling_product)
                        report["fixed"] += 1
                    continue

                divergences = diff_fields(bling_product, ploomes_product, self.settings)
                if divergences:
                    report["divergent"].append({"code": code, "fields": divergences})
                    logger.warning("%s reconcile DIVERGENT code=%s fields=%s", SYNC_PREFIX, code, divergences)
                    if apply_fixes:
                        self.upsert_from_bling_product(bling_product)
                        report["fixed"] += 1
                else:
                    report["ok"] += 1
            except Exception as exc:
                report["errors"] += 1
                logger.exception(
                    "%s reconcile ERRO bling_id=%s | %s",
                    SYNC_PREFIX,
                    summary.get("id"),
                    exc,
                )

        report["orphan_in_ploomes"] = [
            code for code in ploomes_by_code if code not in seen_codes
        ]
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)

        logger.info(
            "%s FIM reconcile | ok=%s fixed=%s missing=%s divergent=%s errors=%s elapsed=%ss",
            SYNC_PREFIX,
            report["ok"],
            report["fixed"],
            len(report["missing_in_ploomes"]),
            len(report["divergent"]),
            report["errors"],
            report["elapsed_seconds"],
        )
        return report
