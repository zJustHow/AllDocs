import io
from functools import lru_cache

from minio import Minio

from app.config import Settings, get_settings


@lru_cache
def get_minio_client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


class StorageService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = get_minio_client()
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.settings.minio_bucket):
            self.client.make_bucket(self.settings.minio_bucket)

    def upload(self, object_key: str, data: bytes, content_type: str) -> str:
        self.client.put_object(
            self.settings.minio_bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return object_key

    def download(self, object_key: str) -> bytes:
        response = self.client.get_object(self.settings.minio_bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def try_download(self, object_key: str) -> bytes | None:
        try:
            return self.download(object_key)
        except Exception:
            return None

    def delete(self, object_key: str) -> None:
        self.client.remove_object(self.settings.minio_bucket, object_key)
