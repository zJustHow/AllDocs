from types import SimpleNamespace
from unittest.mock import MagicMock

from app.observability import bind_context, clear_context
from app.workers.enqueue import enqueue


def test_enqueue_propagates_request_id_to_celery_headers() -> None:
    task = MagicMock()
    task.name = "example_task"
    task.apply_async.return_value = SimpleNamespace(id="task-123")
    bind_context(request_id="request-123")
    try:
        result = enqueue(task, "argument")
    finally:
        clear_context()

    assert result.id == "task-123"
    task.apply_async.assert_called_once_with(
        args=("argument",),
        headers={"request_id": "request-123"},
    )
