"""Persistencia do contador diario de requisicoes (arquivo local ou GCS).

Segue o mesmo padrao de token_store: FileQuotaStore para execucao local
(CLI blng_fetcher) e GcsQuotaStore para Cloud Run, compartilhando o mesmo
bucket dos tokens. O contador guarda apenas {date, count} do dia corrente.
"""
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


class QuotaStore(ABC):
    @abstractmethod
    def load(self) -> dict | None:
        pass

    @abstractmethod
    def save(self, date: str, count: int) -> None:
        pass


class FileQuotaStore(QuotaStore):
    def __init__(self, path: str):
        self.path = Path(path)

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            with self.path.open(encoding="utf-8") as file:
                return json.load(file)
        except (ValueError, OSError):
            return None

    def save(self, date: str, count: int) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as file:
            json.dump({"date": date, "count": count}, file)
        tmp.replace(self.path)


class GcsQuotaStore(QuotaStore):
    def __init__(self, bucket_name: str, blob_name: str = "bling/quota.json"):
        self.bucket_name = bucket_name
        self.blob_name = blob_name

    def _blob(self):
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(self.bucket_name)
        return bucket.blob(self.blob_name)

    def load(self) -> dict | None:
        blob = self._blob()
        if not blob.exists():
            return None
        try:
            return json.loads(blob.download_as_text(encoding="utf-8"))
        except ValueError:
            return None

    def save(self, date: str, count: int) -> None:
        self._blob().upload_from_string(
            json.dumps({"date": date, "count": count}),
            content_type="application/json",
        )


def build_quota_store(quota_path: str, gcs_bucket: str) -> QuotaStore:
    if gcs_bucket:
        return GcsQuotaStore(gcs_bucket)
    return FileQuotaStore(quota_path)
