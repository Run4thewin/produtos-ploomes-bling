import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class TokenStore(ABC):
    @abstractmethod
    def load(self) -> dict | None:
        pass

    @abstractmethod
    def save(self, access_token: str, refresh_token: str, expires_at: datetime) -> None:
        pass


class FileTokenStore(TokenStore):
    def __init__(self, path: str):
        self.path = Path(path)

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        with self.path.open(encoding="utf-8") as file:
            data = json.load(file)
        data["token_expiration_time"] = datetime.fromisoformat(
            data["token_expiration_time"]
        )
        return data

    def save(self, access_token: str, refresh_token: str, expires_at: datetime) -> None:
        payload = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expiration_time": expires_at.isoformat(),
        }
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(payload, file)
        logger.info("Tokens Bling salvos em %s", self.path)


class GcsTokenStore(TokenStore):
    def __init__(self, bucket_name: str, blob_name: str = "bling/tokens.json"):
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
        data = json.loads(blob.download_as_text(encoding="utf-8"))
        data["token_expiration_time"] = datetime.fromisoformat(
            data["token_expiration_time"]
        )
        return data

    def save(self, access_token: str, refresh_token: str, expires_at: datetime) -> None:
        payload = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expiration_time": expires_at.isoformat(),
        }
        self._blob().upload_from_string(
            json.dumps(payload),
            content_type="application/json",
        )
        logger.info("Tokens Bling salvos em gs://%s/%s", self.bucket_name, self.blob_name)


def build_token_store(tokens_path: str, gcs_bucket: str) -> TokenStore:
    if gcs_bucket:
        return GcsTokenStore(gcs_bucket)
    return FileTokenStore(tokens_path)
