from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import shutil
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
    start_http_server,
)
from prometheus_client import REGISTRY
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)
task_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("task_id", default="")

HTTP_REQUESTS = Counter(
    "alldocs_http_requests_total",
    "HTTP requests completed by the API.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "alldocs_http_request_duration_seconds",
    "End-to-end HTTP request duration, including streaming responses.",
    ("method", "route"),
)
HTTP_IN_PROGRESS = Gauge(
    "alldocs_http_requests_in_progress",
    "HTTP requests currently being served.",
    ("method",),
)
TASKS = Counter(
    "alldocs_celery_tasks_total",
    "Celery tasks completed by state.",
    ("task", "state"),
)
TASK_DURATION = Histogram(
    "alldocs_celery_task_duration_seconds",
    "Celery task execution duration.",
    ("task",),
)
STAGE_DURATION = Histogram(
    "alldocs_stage_duration_seconds",
    "Duration of named backend processing stages.",
    ("component", "stage"),
)

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_RESERVED_LOG_FIELDS = set(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
}


def current_request_id() -> str:
    return request_id_var.get()


def current_task_id() -> str:
    return task_id_var.get()


def bind_context(*, request_id: str = "", task_id: str = "") -> None:
    request_id_var.set(request_id)
    task_id_var.set(task_id)


def clear_context() -> None:
    bind_context()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = current_request_id()
        task_id = current_task_id()
        if request_id:
            payload["request_id"] = request_id
        if task_id:
            payload["task_id"] = task_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_FIELDS and not key.startswith("_"):
                payload[key] = _json_safe(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return str(value)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def _request_id_from_scope(scope: Scope) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == b"x-request-id":
            candidate = value.decode("latin-1").strip()
            if _REQUEST_ID_PATTERN.fullmatch(candidate):
                return candidate
    return uuid.uuid4().hex


def _route_name(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else "__unmatched__"


class RequestObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger("alldocs.http")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from_scope(scope)
        request_token = request_id_var.set(request_id)
        task_token = task_id_var.set("")
        method = scope.get("method", "UNKNOWN")
        status = 500
        completed = False
        started = time.perf_counter()
        HTTP_IN_PROGRESS.labels(method=method).inc()

        async def send_with_context(message: Message) -> None:
            nonlocal status, completed
            if message["type"] == "http.response.start":
                status = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True
                self._complete(scope, method, status, started)

        try:
            await self.app(scope, receive, send_with_context)
        except Exception:
            if not completed:
                self._complete(scope, method, 500, started, failed=True)
            raise
        finally:
            HTTP_IN_PROGRESS.labels(method=method).dec()
            request_id_var.reset(request_token)
            task_id_var.reset(task_token)

    def _complete(
        self,
        scope: Scope,
        method: str,
        status: int,
        started: float,
        *,
        failed: bool = False,
    ) -> None:
        route = _route_name(scope)
        duration = time.perf_counter() - started
        HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
        HTTP_DURATION.labels(method=method, route=route).observe(duration)
        log = self.logger.exception if failed else self.logger.info
        log(
            "http_request_completed",
            extra={
                "event": "http_request_completed",
                "method": method,
                "route": route,
                "path": scope.get("path", ""),
                "status": status,
                "duration_ms": round(duration * 1000, 2),
            },
        )


@contextmanager
def timed_stage(component: str, stage: str, **fields: Any) -> Iterator[None]:
    started = time.perf_counter()
    logger = logging.getLogger(f"alldocs.{component}")
    try:
        yield
    except Exception:
        duration = time.perf_counter() - started
        STAGE_DURATION.labels(component=component, stage=stage).observe(duration)
        logger.exception(
            "stage_failed",
            extra={
                "event": "stage_failed",
                "component": component,
                "stage": stage,
                "duration_ms": round(duration * 1000, 2),
                **fields,
            },
        )
        raise
    else:
        duration = time.perf_counter() - started
        STAGE_DURATION.labels(component=component, stage=stage).observe(duration)
        logger.info(
            "stage_completed",
            extra={
                "event": "stage_completed",
                "component": component,
                "stage": stage,
                "duration_ms": round(duration * 1000, 2),
                **fields,
            },
        )


def record_stage_duration(
    component: str,
    stage: str,
    started: float,
    **fields: Any,
) -> None:
    duration = time.perf_counter() - started
    STAGE_DURATION.labels(component=component, stage=stage).observe(duration)
    logging.getLogger(f"alldocs.{component}").info(
        "stage_completed",
        extra={
            "event": "stage_completed",
            "component": component,
            "stage": stage,
            "duration_ms": round(duration * 1000, 2),
            **fields,
        },
    )


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def start_worker_metrics_server(port: int, multiprocess_dir: str) -> None:
    path = Path(multiprocess_dir)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    start_http_server(port, registry=registry)


def prometheus_multiprocess_dir() -> str:
    return os.environ.get("PROMETHEUS_MULTIPROC_DIR", "/tmp/alldocs-prometheus")
