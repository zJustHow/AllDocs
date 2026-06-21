import json
import logging

from app.observability import JsonFormatter, bind_context, clear_context


def test_json_formatter_includes_context_and_extra_fields() -> None:
    bind_context(request_id="request-1", task_id="task-1")
    try:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="completed",
            args=(),
            exc_info=None,
        )
        record.event = "unit_test"
        record.duration_ms = 12.5

        payload = json.loads(JsonFormatter().format(record))
    finally:
        clear_context()

    assert payload["message"] == "completed"
    assert payload["request_id"] == "request-1"
    assert payload["task_id"] == "task-1"
    assert payload["event"] == "unit_test"
    assert payload["duration_ms"] == 12.5
