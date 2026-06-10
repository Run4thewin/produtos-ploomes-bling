import base64
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from app.clients.token_store import TokenStore, build_token_store
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class BlingClient:
    def __init__(self, settings: Settings | None = None, token_store: TokenStore | None = None):
        self.settings = settings or get_settings()
        self.token_store = token_store or build_token_store(
            self.settings.bling_tokens_path,
            self.settings.gcs_bucket,
        )
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at = datetime.min

    def _auth_headers(self) -> dict[str, str]:
        token = self.get_access_token()
        return {
            "accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def get_access_token(self) -> str:
        if self._access_token and datetime.now() < self._expires_at:
            return self._access_token

        stored = self.token_store.load()
        if stored:
            self._access_token = stored.get("access_token")
            self._refresh_token = stored.get("refresh_token")
            self._expires_at = stored.get("token_expiration_time", datetime.min)

        if self._access_token and datetime.now() < self._expires_at:
            return self._access_token

        if not self._refresh_token:
            legacy_token = self._refresh_via_legacy_oauth()
            if legacy_token:
                return legacy_token
            raise RuntimeError(
                "Refresh token do Bling ausente. Execute o OAuth no projeto legado "
                "ploomes_bling ou envie tokens.json para o bucket GCS."
            )

        try:
            token_info = self._refresh_access_token(self._refresh_token)
        except httpx.HTTPError:
            logger.warning("Falha ao renovar token via API; tentando OAuth legado")
            legacy_token = self._refresh_via_legacy_oauth()
            if legacy_token:
                return legacy_token
            raise

        self._access_token = token_info["access_token"]
        self._refresh_token = token_info.get("refresh_token", self._refresh_token)
        expires_in = int(token_info.get("expires_in", 3600))
        self._expires_at = datetime.now() + timedelta(seconds=expires_in)
        self.token_store.save(self._access_token, self._refresh_token, self._expires_at)
        return self._access_token

    def _refresh_via_legacy_oauth(self) -> str | None:
        legacy_path = Path(self.settings.legacy_ploomes_bling_path)
        if not legacy_path.exists():
            return None

        legacy_module_path = str(legacy_path)
        if legacy_module_path not in sys.path:
            sys.path.insert(0, legacy_module_path)

        try:
            from get_autorization_token_bling import (
                get_authorization_token_bling,
                get_new_authorization_token_bling,
                refresh_access_token,
            )

            token = get_authorization_token_bling()
            if not token:
                stored = self.token_store.load()
                refresh_token = stored.get("refresh_token") if stored else None
                token_info = None
                if refresh_token:
                    token_info = refresh_access_token(refresh_token)
                if not token_info:
                    logger.info("Abrindo OAuth Bling via Selenium (projeto legado)")
                    token_info = get_new_authorization_token_bling()
                if not token_info:
                    return None
                expires_in = int(token_info.get("expires_in", 3600))
                expires_at = datetime.now() + timedelta(seconds=expires_in)
                self.token_store.save(
                    token_info["access_token"],
                    token_info.get("refresh_token", refresh_token or ""),
                    expires_at,
                )
                token = token_info["access_token"]

            stored = self.token_store.load()
            if stored:
                self._access_token = stored.get("access_token")
                self._refresh_token = stored.get("refresh_token")
                self._expires_at = stored.get("token_expiration_time", datetime.min)
            else:
                self._access_token = token
            logger.info("Token Bling obtido via modulo legado ploomes_bling")
            return token
        except Exception as exc:
            logger.warning("OAuth legado indisponivel: %s", exc)
            return None
        finally:
            if legacy_module_path in sys.path:
                sys.path.remove(legacy_module_path)

    def _refresh_access_token(self, refresh_token: str) -> dict:
        credentials = f"{self.settings.bling_client_id}:{self.settings.bling_client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        response = httpx.post(
            "https://www.bling.com.br/Api/v3/oauth/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "1.0",
                "Authorization": f"Basic {encoded}",
            },
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            timeout=self.settings.http_timeout_seconds,
        )
        response.raise_for_status()
        logger.info("Access token Bling renovado")
        return response.json()

    def _raise_bling_error(self, response: httpx.Response) -> None:
        if response.status_code == 403:
            body = response.json() if response.content else {}
            if body.get("error", {}).get("type") == "insufficient_scope":
                raise RuntimeError(
                    "App Bling sem escopo 'product'. No portal developer.bling.com.br, "
                    "adicione o escopo de Produtos ao app e rode scripts/refresh_bling_token.ps1"
                )
        response.raise_for_status()

    def get_product_by_code(self, code: str) -> dict | None:
        response = httpx.get(
            f"{self.settings.bling_api_base}/produtos",
            headers=self._auth_headers(),
            params={"codigo": code, "limite": 1, "pagina": 1},
            timeout=self.settings.http_timeout_seconds,
        )
        self._raise_bling_error(response)
        items = response.json().get("data", [])
        return items[0] if items else None

    def create_product(self, payload: dict) -> dict:
        response = httpx.post(
            f"{self.settings.bling_api_base}/produtos",
            headers=self._auth_headers(),
            json=payload,
            timeout=self.settings.http_timeout_seconds,
        )
        self._raise_bling_error(response)
        body = response.json()
        return body.get("data", body)

    def update_product(self, product_id: int | str, payload: dict) -> dict:
        response = httpx.put(
            f"{self.settings.bling_api_base}/produtos/{product_id}",
            headers=self._auth_headers(),
            json=payload,
            timeout=self.settings.http_timeout_seconds,
        )
        self._raise_bling_error(response)
        body = response.json()
        return body.get("data", body)

    def get_product(self, product_id: int | str) -> dict:
        response = httpx.get(
            f"{self.settings.bling_api_base}/produtos/{product_id}",
            headers=self._auth_headers(),
            timeout=self.settings.http_timeout_seconds,
        )
        self._raise_bling_error(response)
        return response.json()["data"]

    def iter_products(self, page_size: int = 100):
        page = 1
        while True:
            response = httpx.get(
                f"{self.settings.bling_api_base}/produtos",
                headers=self._auth_headers(),
                params={"pagina": page, "limite": page_size},
                timeout=self.settings.http_timeout_seconds,
            )
            self._raise_bling_error(response)
            payload = response.json()
            items = payload.get("data", [])
            if not items:
                break
            for item in items:
                yield item
            if len(items) < page_size:
                break
            page += 1
