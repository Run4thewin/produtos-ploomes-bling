import unittest
from unittest.mock import patch

import httpx

from app.clients.ploomes import PloomesClient
from app.config import Settings


class PloomesRateLimitTest(unittest.TestCase):
    def test_retries_after_rate_limit(self):
        url = "https://api2.ploomes.com/Products"
        request = httpx.Request("GET", url)
        rate_limited = httpx.Response(
            429,
            headers={"Retry-After": "0.1"},
            request=request,
        )
        success = httpx.Response(
            200,
            json={"value": [{"Id": 1, "Code": "ABC123"}]},
            request=request,
        )
        client = PloomesClient(Settings(ploomes_min_request_interval_seconds=0))

        with (
            patch("app.clients.ploomes.httpx.request", side_effect=[rate_limited, success]) as request_mock,
            patch("app.clients.rate_limit.time.sleep") as sleep_mock,
        ):
            result = client.get_product_by_code("ABC123")

        self.assertEqual(result, {"Id": 1, "Code": "ABC123"})
        self.assertEqual(request_mock.call_count, 2)
        sleep_mock.assert_called_once_with(0.1)


if __name__ == "__main__":
    unittest.main()
