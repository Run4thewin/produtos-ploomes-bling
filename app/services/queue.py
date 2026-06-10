import json
import logging
from typing import Literal

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

Direction = Literal["bling", "ploomes"]


class ProductEventQueue:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def enqueue_bling(self, product_id: int | str, action: str, event_id: str | None = None) -> None:
        self._enqueue(
            direction="bling",
            payload={
                "product_id": str(product_id),
                "action": action,
                "event_id": event_id,
            },
            process_path="/tasks/process-bling-product",
            processor=lambda: self._process_bling(product_id, action),
        )

    def enqueue_ploomes(self, product_id: int | str, action: str) -> None:
        self._enqueue(
            direction="ploomes",
            payload={
                "product_id": str(product_id),
                "action": action,
            },
            process_path="/tasks/process-ploomes-product",
            processor=lambda: self._process_ploomes(product_id, action),
        )

    def _enqueue(
        self,
        direction: Direction,
        payload: dict,
        process_path: str,
        processor,
    ) -> None:
        if self.settings.cloud_tasks_enabled:
            self._enqueue_cloud_task(payload, process_path)
            return

        logger.info("Processamento direto (%s): %s", direction, payload)
        processor()

    def _process_bling(self, product_id: int | str, action: str) -> None:
        from app.services.sync import ProductSyncService

        ProductSyncService(self.settings).upsert_from_bling_id(product_id, action)

    def _process_ploomes(self, product_id: int | str, action: str) -> None:
        from app.services.sync_ploomes_to_bling import PloomesToBlingSyncService

        PloomesToBlingSyncService(self.settings).upsert_from_ploomes_id(product_id, action)

    def _enqueue_cloud_task(self, payload: dict, process_path: str) -> None:
        from google.cloud import tasks_v2
        from google.protobuf import duration_pb2

        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(
            self.settings.gcp_project,
            self.settings.cloud_tasks_location,
            self.settings.cloud_tasks_queue,
        )

        http_request: dict = {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{self.settings.service_url.rstrip('/')}{process_path}",
            "headers": {
                "Content-Type": "application/json",
                "X-Internal-Secret": self.settings.internal_secret,
            },
            "body": json.dumps(payload).encode("utf-8"),
        }

        if self.settings.cloud_tasks_service_account:
            http_request["oidc_token"] = {
                "service_account_email": self.settings.cloud_tasks_service_account,
                "audience": self.settings.service_url.rstrip("/"),
            }

        task = {
            "http_request": http_request,
            "dispatch_deadline": duration_pb2.Duration(seconds=1800),
        }

        client.create_task(request={"parent": parent, "task": task})
        logger.info("Evento enfileirado no Cloud Tasks: %s", payload)
