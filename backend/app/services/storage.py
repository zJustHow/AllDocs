import io
from functools import lru_cache
from threading import Lock

from minio import Minio

from app.config import Settings, get_settings

_bucket_lock = Lock()
_bucket_ready = False


@lru_cache
def get_minio_client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_bucket(settings: Settings | None = None) -> None:
    global _bucket_ready
    if _bucket_ready:
        return
    with _bucket_lock:
        if _bucket_ready:
            return
        settings = settings or get_settings()
        client = get_minio_client()
        if not client.bucket_exists(settings.minio_bucket):
            client.make_bucket(settings.minio_bucket)
        _bucket_ready = True


class StorageService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = get_minio_client()

    def upload(self, object_key: str, data: bytes, content_type: str) -> str:
        ensure_bucket(self.settings)
        self.client.put_object(
            self.settings.minio_bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return object_key

    def download(self, object_key: str) -> bytes:
        ensure_bucket(self.settings)
        response = self.client.get_object(self.settings.minio_bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def delete(self, object_key: str) -> None:
        self.client.remove_object(self.settings.minio_bucket, object_key)

    def delete_prefix(self, prefix: str) -> None:
        for obj in self.client.list_objects(
            self.settings.minio_bucket,
            prefix=prefix,
            recursive=True,
        ):
            self.client.remove_object(self.settings.minio_bucket, obj.object_name)
