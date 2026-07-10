import logging
import time
from urllib.parse import quote

import httpx

from app.clients.rate_limit import get_api_rate_limiter, retry_after_delay
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

PLOOMES_TRANSIENT_STATUS = {429, 502, 503, 504}
PLOOMES_RETRY_DELAYS = (1.0, 2.0, 5.0, 10.0, 20.0)
PLOOMES_MAX_RETRY_AFTER_SECONDS = 60.0


class PloomesClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._rate_limiter = get_api_rate_limiter(
            "Ploomes",
            self.settings.ploomes_min_request_interval_seconds,
        )

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

        max_attempts = len(PLOOMES_RETRY_DELAYS) + 1
        for attempt in range(1, max_attempts + 1):
            try:
                self._rate_limiter.wait()
                started = time.monotonic()
                response = httpx.request(
                    method,
                    f"{self.settings.ploomes_api_base}/{path.lstrip('/')}",
                    headers=self._headers(),
                    timeout=timeout,
                    **kwargs,
                )
                elapsed_ms = round((time.monotonic() - started) * 1000)
                logger.info(
                    "Ploomes HTTP | method=%s path=%s status=%s attempt=%s elapsed_ms=%s",
                    method,
                    path,
                    response.status_code,
                    attempt,
                    elapsed_ms,
                )
                if response.status_code not in PLOOMES_TRANSIENT_STATUS:
                    return response

                last_error = RuntimeError(
                    f"Ploomes retornou HTTP {response.status_code}: {response.text[:300]}"
                )
                if response.status_code == 429 and attempt < max_attempts:
                    delay = retry_after_delay(
                        response,
                        PLOOMES_RETRY_DELAYS[attempt - 1],
                        max_delay=PLOOMES_MAX_RETRY_AFTER_SECONDS,
                    )
                    logger.warning(
                        "Ploomes retornou 429 em %s %s; aguardando %.1fs antes da tentativa %s",
                        method,
                        path,
                        delay,
                        attempt + 1,
                    )
                    self._rate_limiter.wait_after_429(delay)
                    continue

                logger.warning(
                    "Ploomes instavel (%s %s) tentativa %s/%s: HTTP %s",
                    method,
                    path,
                    attempt,
                    max_attempts,
                    response.status_code,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning(
                    "Timeout no Ploomes (%s %s) tentativa %s/%s",
                    method,
                    path,
                    attempt,
                    max_attempts,
                )

            if attempt < max_attempts:
                time.sleep(PLOOMES_RETRY_DELAYS[attempt - 1])

        raise RuntimeError(f"Ploomes indisponivel apos {max_attempts} tentativas: {last_error}")

    def get_product_by_id(self, product_id: int | str) -> dict:
        # Ploomes nao aceita acesso por chave Products(id) (retorna 404);
        # e preciso usar $filter=Id eq {id}, como em get_deal_by_id.
        response = self._request(
            "GET",
            "Products",
            params={
                "$filter": f"Id eq {product_id}",
                "$top": 1,
                "$expand": "OtherProperties",
            },
        )
        self._raise_ploomes_error(response)
        values = response.json().get("value", [])
        if not values:
            raise RuntimeError(f"Produto Ploomes nao encontrado: {product_id}")
        return values[0]

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

    def iter_product_codes(self, page_size: int = 1000):
        """Itera apenas o campo Code (listagem enxuta, sem $expand).

        Usado para pre-indexar os produtos ja existentes no Ploomes e evitar
        1 GET de lookup por produto no full-sync.
        """
        skip = 0
        while True:
            response = self._request(
                "GET",
                "Products",
                params={
                    "$top": page_size,
                    "$skip": skip,
                    "$select": "Code",
                },
            )
            self._raise_ploomes_error(response)
            values = response.json().get("value", [])
            if not values:
                break
            for item in values:
                yield item.get("Code")
            if len(values) < page_size:
                break
            skip += page_size
