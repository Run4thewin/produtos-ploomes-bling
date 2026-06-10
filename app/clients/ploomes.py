import logging
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class PloomesClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _headers(self) -> dict[str, str]:
        return {
            "User-Key": self.settings.ploomes_user_key,
            "Content-Type": "application/json",
        }

    def get_product_by_id(self, product_id: int | str) -> dict:
        response = httpx.get(
            f"{self.settings.ploomes_api_base}/Products({product_id})",
            headers=self._headers(),
            params={"$expand": "OtherProperties"},
            timeout=self.settings.http_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def get_product_by_code(self, code: str) -> dict | None:
        safe_code = code.replace("'", "''")
        response = httpx.get(
            f"{self.settings.ploomes_api_base}/Products",
            headers=self._headers(),
            params={
                "$filter": f"Code eq '{safe_code}'",
                "$top": 1,
                "$expand": "OtherProperties",
            },
            timeout=self.settings.http_timeout_seconds,
        )
        response.raise_for_status()
        values = response.json().get("value", [])
        return values[0] if values else None

    def create_product(self, payload: dict) -> dict:
        response = httpx.post(
            f"{self.settings.ploomes_api_base}/Products",
            headers=self._headers(),
            json=payload,
            timeout=self.settings.http_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def update_product(self, product_id: int, payload: dict) -> dict:
        response = httpx.patch(
            f"{self.settings.ploomes_api_base}/Products({product_id})",
            headers=self._headers(),
            json=payload,
            timeout=self.settings.http_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def iter_products(self, page_size: int = 100):
        skip = 0
        while True:
            response = httpx.get(
                f"{self.settings.ploomes_api_base}/Products",
                headers=self._headers(),
                params={
                    "$top": page_size,
                    "$skip": skip,
                    "$select": "Id,Code,Name,UnitPrice,Suspended",
                    "$expand": "OtherProperties",
                },
                timeout=self.settings.http_timeout_seconds,
            )
            response.raise_for_status()
            values = response.json().get("value", [])
            if not values:
                break
            for item in values:
                yield item
            if len(values) < page_size:
                break
            skip += page_size
