import logging
import time

from celery import Celery, signals

from app.config import get_settings
from app.observability import (
    TASK_DURATION,
    TASKS,
    bind_context,
    clear_context,
    configure_logging,
    prometheus_multiprocess_dir,
    start_worker_metrics_server,
)

settings = get_settings()

INGESTION_QUEUE = "ingestion"
MAINTENANCE_QUEUE = "maintenance"

celery_app = Celery("alldocs", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    imports=["app.workers.tasks"],
    # Keep CPU-heavy document processing from blocking short maintenance jobs.
    task_default_queue=MAINTENANCE_QUEUE,
    task_routes={
        "process_document": {"queue": INGESTION_QUEUE},
        "delete_document": {"queue": MAINTENANCE_QUEUE},
    },
)

_task_started: dict[str, float] = {}


def _configure_worker_logging(*_args, **_kwargs) -> None:
    configure_logging(settings.log_level)


def _start_worker_observability(*_args, **_kwargs) -> None:
    if settings.metrics_enabled:
        start_worker_metrics_server(
            settings.metrics_worker_port,
            prometheus_multiprocess_dir(),
        )


def _task_prerun(task_id=None, task=None, **_kwargs) -> None:
    task_id = str(task_id or "")
    headers = getattr(getattr(task, "request", None), "headers", None) or {}
    request_id = str(headers.get("request_id", ""))
    bind_context(request_id=request_id, task_id=task_id)
    _task_started[task_id] = time.perf_counter()
    logging.getLogger("alldocs.celery").info(
        "task_started",
        extra={"event": "task_started", "celery_task": str(getattr(task, "name", "unknown"))},
    )


def _task_postrun(task_id=None, task=None, state=None, **_kwargs) -> None:
    task_id = str(task_id or "")
    task_name = str(getattr(task, "name", "unknown"))
    started = _task_started.pop(task_id, None)
    duration = time.perf_counter() - started if started is not None else None
    if started is not None:
        TASK_DURATION.labels(task=task_name).observe(duration)
    TASKS.labels(task=task_name, state=str(state or "UNKNOWN")).inc()
    logging.getLogger("alldocs.celery").info(
        "task_completed",
        extra={
            "event": "task_completed",
            "celery_task": task_name,
            "state": str(state or "UNKNOWN"),
            "duration_ms": round(duration * 1000, 2) if duration is not None else None,
        },
    )
    clear_context()


signals.setup_logging.connect(_configure_worker_logging)
signals.celeryd_init.connect(_start_worker_observability)
signals.task_prerun.connect(_task_prerun)
signals.task_postrun.connect(_task_postrun)
