from __future__ import annotations

from typing import Any
import logging

from app.observability import current_request_id


def enqueue(task: Any, *args: Any):
    headers: dict[str, str] = {}
    if request_id := current_request_id():
        headers["request_id"] = request_id
    result = task.apply_async(args=args, headers=headers)
    logging.getLogger("alldocs.celery").info(
        "task_enqueued",
        extra={
            "event": "task_enqueued",
            "celery_task": str(getattr(task, "name", "unknown")),
            "enqueued_task_id": str(result.id),
        },
    )
    return result
