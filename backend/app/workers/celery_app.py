from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery("alldocs", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    imports=["app.workers.tasks"],
)
