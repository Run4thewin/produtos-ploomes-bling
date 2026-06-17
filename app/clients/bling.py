import base64
import logging
from datetime import datetime, timedelta

import httpx

from app.clients.token_store import TokenStore, build_token_store
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

TOKEN_REFRESH_SKEW = timedelta(minutes=5)


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

    def _request(
        self,
        method: str,
        path: str,
        *,
        retry_on_unauthorized: bool = True,
        **kwargs,
    ) -> httpx.Response:
        response = httpx.request(
            method,
            f"{self.settings.bling_api_base}/{path.lstrip('/')}",
            headers=self._auth_headers(),
            timeout=self.settings.http_timeout_seconds,
            **kwargs,
        )
        if response.status_code == 401 and retry_on_unauthorized:
            logger.warning("Bling retornou 401; renovando token e tentando novamente")
            self.force_refresh_access_token()
            response = httpx.request(
                method,
                f"{self.settings.bling_api_base}/{path.lstrip('/')}",
                headers=self._auth_headers(),
                timeout=self.settings.http_timeout_seconds,
                **kwargs,
            )
        return response

    def get_access_token(self) -> str:
        if self._has_valid_access_token():
            return self._access_token

        stored = self.token_store.load()
        if stored:
            self._access_token = stored.get("access_token")
            self._refresh_token = stored.get("refresh_token")
            self._expires_at = stored.get("token_expiration_time", datetime.min)

        if self._has_valid_access_token():
            return self._access_token

        if not self._refresh_token:
            raise RuntimeError(
                "Refresh token do Bling ausente. Faca a autorizacao OAuth inicial "
                "uma vez e salve o tokens.json usado pelo servico local/GCS."
            )

        return self._refresh_and_store_access_token(self._refresh_token)

    def force_refresh_access_token(self) -> str:
        stored = self.token_store.load()
        if stored:
            self._refresh_token = stored.get("refresh_token")

        if not self._refresh_token:
            raise RuntimeError(
                "Refresh token do Bling ausente. Faca a autorizacao OAuth inicial "
                "uma vez e salve o tokens.json usado pelo servico local/GCS."
            )

        return self._refresh_and_store_access_token(self._refresh_token)

    def _has_valid_access_token(self) -> bool:
        return bool(
            self._access_token
            and datetime.now() + TOKEN_REFRESH_SKEW < self._expires_at
        )

    def _refresh_and_store_access_token(self, refresh_token: str) -> str:
        try:
            token_info = self._refresh_access_token(refresh_token)
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500] if exc.response is not None else ""
            raise RuntimeError(
                "Nao foi possivel renovar o token do Bling via refresh_token. "
                "Se a resposta for invalid_grant, o refresh token foi revogado/invalidado "
                "e sera necessario refazer somente a autorizacao OAuth inicial. "
                f"Resposta Bling: HTTP {exc.response.status_code} {body}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Erro HTTP ao renovar token do Bling: {exc}") from exc

        self._access_token = token_info["access_token"]
        self._refresh_token = token_info.get("refresh_token", self._refresh_token)
        expires_in = int(token_info.get("expires_in", 3600))
        self._expires_at = datetime.now() + timedelta(seconds=expires_in)
        self.token_store.save(self._access_token, self._refresh_token, self._expires_at)
        return self._access_token

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
        if response.status_code == 401:
            raise RuntimeError(
                "Bling retornou 401 Unauthorized mesmo apos tentativa de renovacao. "
                "Renove o OAuth do Bling e atualize o tokens.json usado pelo servico "
                "local/GCS. Tambem confirme se BLING_CLIENT_ID e BLING_CLIENT_SECRET "
                "sao do mesmo app que gerou o refresh token."
            )
        if response.status_code == 403:
            body = response.json() if response.content else {}
            error_type = body.get("error", {}).get("type")
            if error_type == "insufficient_scope":
                scope = body.get("error", {}).get("description", "escopo insuficiente")
                raise RuntimeError(
                    f"App Bling sem permissao para este recurso ({scope}). "
                    "Adicione o escopo no developer.bling.com.br e renove o token."
                )
        response.raise_for_status()

    def search_contacts(
        self,
        pesquisa: str | None = None,
        numero_documento: str | None = None,
        pagina: int = 1,
        limite: int = 20,
        criterio: int | None = None,
        telefone: str | None = None,
        uf: str | None = None,
        tipo_pessoa: int | None = None,
    ) -> dict:
        params: dict[str, str | int] = {"pagina": pagina, "limite": limite}
        if pesquisa:
            params["pesquisa"] = pesquisa
        if numero_documento:
            params["numeroDocumento"] = numero_documento
        if criterio is not None:
            params["criterio"] = criterio
        if telefone:
            params["telefone"] = telefone
        if uf:
            params["uf"] = uf
        if tipo_pessoa is not None:
            params["tipoPessoa"] = tipo_pessoa

        response = self._request(
            "GET",
            "contatos",
            params=params,
        )
        self._raise_bling_error(response)
        return response.json()

    def get_contact(self, contact_id: int | str) -> dict:
        response = self._request("GET", f"contatos/{contact_id}")
        self._raise_bling_error(response)
        return response.json()["data"]

    def get_contact_by_document(self, document_number: str | None) -> dict | None:
        if not document_number:
            return None
        result = self.search_contacts(numero_documento=document_number, limite=1)
        contacts = result.get("data", [])
        return contacts[0] if contacts else None

    def _summarize_company_with_contacts(self, detail: dict) -> dict:
        return {
            "id": detail.get("id"),
            "nome": detail.get("nome"),
            "numeroDocumento": detail.get("numeroDocumento"),
            "tipo": detail.get("tipo"),
            "email": detail.get("email"),
            "telefone": detail.get("telefone"),
            "pessoasContato": detail.get("pessoasContato") or [],
        }

    def list_companies_with_contacts(
        self,
        pagina: int = 1,
        limite: int = 20,
        apenas_com_vinculos: bool = False,
        max_paginas_busca: int = 10,
    ) -> dict:
        """Lista empresas PJ do Bling com pessoasContato agregadas do detalhe."""
        empresas: list[dict] = []
        pagina_atual = pagina
        paginas_consultadas = 0

        while len(empresas) < limite and paginas_consultadas < max_paginas_busca:
            result = self.search_contacts(
                pagina=pagina_atual,
                limite=limite,
                tipo_pessoa=2,
            )
            contacts = result.get("data", [])
            if not contacts:
                break

            for item in contacts:
                detail = self.get_contact(item["id"])
                if detail.get("tipo") != "J":
                    continue
                pessoas = detail.get("pessoasContato") or []
                if apenas_com_vinculos and not pessoas:
                    continue
                empresas.append(self._summarize_company_with_contacts(detail))
                if len(empresas) >= limite:
                    break

            paginas_consultadas += 1
            if len(contacts) < limite:
                break
            if len(empresas) >= limite:
                break
            pagina_atual += 1

        return {
            "pagina": pagina,
            "limite": limite,
            "total_retornado": len(empresas),
            "paginas_consultadas": paginas_consultadas,
            "empresas": empresas,
        }

    def get_product_by_code(self, code: str) -> dict | None:
        response = self._request(
            "GET",
            "produtos",
            params={"codigo": code, "limite": 1, "pagina": 1},
        )
        self._raise_bling_error(response)
        items = response.json().get("data", [])
        return items[0] if items else None

    def create_product(self, payload: dict) -> dict:
        response = self._request(
            "POST",
            "produtos",
            json=payload,
        )
        self._raise_bling_error(response)
        body = response.json()
        return body.get("data", body)

    def update_product(self, product_id: int | str, payload: dict) -> dict:
        response = self._request(
            "PUT",
            f"produtos/{product_id}",
            json=payload,
        )
        self._raise_bling_error(response)
        body = response.json()
        return body.get("data", body)

    def create_sales_order(self, payload: dict) -> dict:
        response = self._request(
            "POST",
            "pedidos/vendas",
            json=payload,
        )
        self._raise_bling_error(response)
        body = response.json()
        return body.get("data", body)

    def get_sales_order(self, order_id: int | str) -> dict:
        response = self._request("GET", f"pedidos/vendas/{order_id}")
        self._raise_bling_error(response)
        return response.json()["data"]

    def get_product(self, product_id: int | str) -> dict:
        response = self._request("GET", f"produtos/{product_id}")
        self._raise_bling_error(response)
        return response.json()["data"]

    def iter_products(self, page_size: int = 100):
        page = 1
        while True:
            response = self._request(
                "GET",
                "produtos",
                params={"pagina": page, "limite": page_size},
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
