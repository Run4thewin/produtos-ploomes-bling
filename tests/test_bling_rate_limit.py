import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import httpx

from app.clients.bling import BlingClient, build_bling_oauth_headers
from app.config import Settings


class FakeTokenStore:
    def load(self) -> dict:
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "token_expiration_time": datetime.now() + timedelta(hours=1),
        }

    def save(self, access_token: str, refresh_token: str, expires_at: datetime) -> None:
        pass


class BlingRateLimitTest(unittest.TestCase):
    def test_oauth_headers_request_jwt_tokens(self):
        headers = build_bling_oauth_headers("client-id", "client-secret")

        self.assertEqual(headers["enable-jwt"], "1")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertTrue(headers["Authorization"].startswith("Basic "))

    def test_create_sales_order_retries_after_rate_limit(self):
        url = "https://api.bling.com.br/Api/v3/pedidos/vendas"
        request = httpx.Request("POST", url)
        rate_limited = httpx.Response(
            429,
            headers={"Retry-After": "0.1"},
            request=request,
        )
        success = httpx.Response(
            201,
            json={"data": {"id": 12345}},
            request=request,
        )
        client = BlingClient(
            Settings(bling_min_request_interval_seconds=0),
            token_store=FakeTokenStore(),
        )

        with (
            patch("app.clients.bling.httpx.request", side_effect=[rate_limited, success]) as request_mock,
            patch("app.clients.bling.time.sleep") as sleep_mock,
        ):
            result = client.create_sales_order({"contato": {"id": 1}})

        self.assertEqual(result, {"id": 12345})
        self.assertEqual(request_mock.call_count, 2)
        sleep_mock.assert_called_once_with(0.1)


if __name__ == "__main__":
    unittest.main()
