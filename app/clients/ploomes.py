import logging
import time
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

PLOOMES_TRANSIENT_STATUS = {502, 503, 504}


class PloomesClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _headers(self) -> dict[str, str]:
        return {
            "user-key": self.settings.ploomes_user_key,
            "Content-Type": "application/json",
        }

    def _raise_ploomes_error(self, response: httpx.Response) -> None:
        if response.status_code == 401:
            raise RuntimeError(
                "Ploomes retornou 401 Unauthorized. Verifique se PLOOMES_USER_KEY "
                "esta configurada no Cloud Run e se o secret ploomes-user-key contem "
                "a chave valida do usuario de integracao."
            )
        response.raise_for_status()

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        timeout = min(float(self.settings.http_timeout_seconds), 10.0)
        last_error: Exception | None = None

        for attempt in range(1, 4):
            try:
                response = httpx.request(
                    method,
                    f"{self.settings.ploomes_api_base}/{path.lstrip('/')}",
                    headers=self._headers(),
                    timeout=timeout,
                    **kwargs,
                )
                if response.status_code not in PLOOMES_TRANSIENT_STATUS:
                    return response

                last_error = RuntimeError(
                    f"Ploomes retornou HTTP {response.status_code}: {response.text[:300]}"
                )
                logger.warning(
                    "Ploomes instavel (%s %s) tentativa %s/3: HTTP %s",
                    method,
                    path,
                    attempt,
                    response.status_code,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning(
                    "Timeout no Ploomes (%s %s) tentativa %s/3",
                    method,
                    path,
                    attempt,
                )

            if attempt < 3:
                time.sleep(0.5 * attempt)

        raise RuntimeError(f"Ploomes indisponivel apos 3 tentativas: {last_error}")

    def get_product_by_id(self, product_id: int | str) -> dict:
        response = self._request(
            "GET",
            f"Products({product_id})",
            params={"$expand": "OtherProperties"},
        )
        self._raise_ploomes_error(response)
        return response.json()

    def get_product_by_code(self, code: str) -> dict | None:
        safe_code = code.replace("'", "''")
        response = self._request(
            "GET",
            "Products",
            params={
                "$filter": f"Code eq '{safe_code}'",
                "$top": 1,
                "$expand": "OtherProperties",
            },
        )
        self._raise_ploomes_error(response)
        values = response.json().get("value", [])
        return values[0] if values else None

    def create_product(self, payload: dict) -> dict:
        response = self._request(
            "POST",
            "Products",
            json=payload,
        )
        self._raise_ploomes_error(response)
        return response.json()

    def update_product(self, product_id: int, payload: dict) -> dict:
        response = self._request(
            "PATCH",
            f"Products({product_id})",
            json=payload,
        )
        self._raise_ploomes_error(response)
        return response.json()

    def get_deal_by_id(self, deal_id: int | str) -> dict:
        response = self._request(
            "GET",
            "Deals",
            params={
                "$filter": f"Id eq {deal_id}",
                "$top": 1,
                "$expand": "OtherProperties,Contact",
            },
        )
        self._raise_ploomes_error(response)
        values = response.json().get("value", [])
        if not values:
            raise RuntimeError(f"Deal Ploomes nao encontrado: {deal_id}")
        return values[0]

    def get_latest_quote_by_deal(self, deal_id: int | str) -> dict | None:
        response = self._request(
            "GET",
            "Quotes",
            params={
                "$filter": f"DealId eq {deal_id}",
                "$top": 1,
                "$expand": "Products,Pages,OtherProperties",
                "$orderby": "Id desc",
            },
        )
        self._raise_ploomes_error(response)
        values = response.json().get("value", [])
        return values[0] if values else None

    def update_deal(self, deal_id: int | str, payload: dict) -> dict:
        response = self._request(
            "PATCH",
            f"Deals({deal_id})",
            json=payload,
        )
        self._raise_ploomes_error(response)
        body = response.json() if response.content else {}
        return body.get("value", body)

    def iter_products(self, page_size: int = 100):
        skip = 0
        while True:
            response = self._request(
                "GET",
                "Products",
                params={
                    "$top": page_size,
                    "$skip": skip,
                    "$select": "Id,Code,Name,UnitPrice,Suspended",
                    "$expand": "OtherProperties",
                },
            )
            self._raise_ploomes_error(response)
            values = response.json().get("value", [])
            if not values:
                break
            for item in values:
                yield item
            if len(values) < page_size:
                break
            skip += page_size
