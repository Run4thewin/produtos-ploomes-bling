import unittest

import httpx

from app.config import Settings
from app.services.sync import ProductSyncService


class NotFoundBlingClient:
    def get_product(self, product_id: int | str) -> dict:
        request = httpx.Request("GET", f"https://api.bling.com.br/Api/v3/produtos/{product_id}")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError(
            "Produto nao encontrado",
            request=request,
            response=response,
        )


class UnusedPloomesClient:
    pass


class BlingSyncNotFoundTest(unittest.TestCase):
    def test_update_skips_when_bling_product_no_longer_exists(self):
        service = ProductSyncService(
            Settings(),
            bling=NotFoundBlingClient(),
            ploomes=UnusedPloomesClient(),
        )

        result = service.upsert_from_bling_id("123", "updated")

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["bling_id"], "123")
        self.assertEqual(result["reason"], "produto nao encontrado no Bling")

    def test_delete_skips_when_bling_product_no_longer_exists(self):
        service = ProductSyncService(
            Settings(),
            bling=NotFoundBlingClient(),
            ploomes=UnusedPloomesClient(),
        )

        result = service.upsert_from_bling_id("123", "deleted")

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["bling_id"], "123")
        self.assertEqual(result["reason"], "produto nao encontrado no Bling")


if __name__ == "__main__":
    unittest.main()
