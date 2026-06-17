"""OAuth Bling sem Selenium/Chrome.

Uso:
1. Rode sem argumentos para imprimir a URL de autorizacao.
2. Abra a URL em qualquer navegador, autorize o app e copie o parametro `code`
   da URL final.
3. Rode novamente com --code ou --redirect-url para trocar o code por tokens.
"""

import argparse
import base64
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.clients.token_store import build_token_store
from app.config import get_settings


AUTH_URL = "https://www.bling.com.br/Api/v3/oauth/authorize"
TOKEN_URL = "https://www.bling.com.br/Api/v3/oauth/token"


def extract_code(code: str | None, redirect_url: str | None) -> str | None:
    if code:
        return code.strip()
    if not redirect_url:
        return None
    parsed = urlparse(redirect_url)
    return parse_qs(parsed.query).get("code", [None])[0]


def print_authorization_url() -> None:
    settings = get_settings()
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": settings.bling_client_id,
        "state": state,
    }
    print("Abra esta URL em qualquer navegador e autorize o app Bling:")
    print(f"{AUTH_URL}?{urlencode(params)}")
    print()
    print("Depois rode este script com:")
    print(r'.\.venv\Scripts\python scripts\bling_oauth_manual.py --code "COLE_O_CODE_AQUI"')
    print()
    print("Ou, se preferir, cole a URL final inteira:")
    print(r'.\.venv\Scripts\python scripts\bling_oauth_manual.py --redirect-url "URL_FINAL"')


def exchange_code_for_tokens(code: str) -> None:
    settings = get_settings()
    credentials = f"{settings.bling_client_id}:{settings.bling_client_secret}"
    encoded = base64.b64encode(credentials.encode()).decode()
    response = httpx.post(
        TOKEN_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Authorization": f"Basic {encoded}",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
        },
        timeout=settings.http_timeout_seconds,
    )

    if response.status_code != 200:
        raise SystemExit(
            f"Falha ao trocar code por token: HTTP {response.status_code} - {response.text}"
        )

    token_info = response.json()
    expires_at = datetime.now() + timedelta(seconds=int(token_info.get("expires_in", 3600)))
    store = build_token_store(settings.bling_tokens_path, settings.gcs_bucket)
    store.save(
        token_info["access_token"],
        token_info.get("refresh_token", ""),
        expires_at,
    )
    target = (
        f"gs://{settings.gcs_bucket}/{settings.bling_tokens_path}"
        if settings.gcs_bucket
        else settings.bling_tokens_path
    )
    print(f"Tokens Bling salvos com sucesso em {target}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", help="Parametro code retornado pelo OAuth do Bling.")
    parser.add_argument("--redirect-url", help="URL final completa retornada pelo OAuth do Bling.")
    args = parser.parse_args()

    code = extract_code(args.code, args.redirect_url)
    if not code:
        print_authorization_url()
        return

    exchange_code_for_tokens(code)


if __name__ == "__main__":
    main()
