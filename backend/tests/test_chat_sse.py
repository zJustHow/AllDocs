import json
import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient


def _mock_chat_db() -> AsyncMock:
    db = AsyncMock()
    history_result = MagicMock()
    history_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=history_result)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


class _MockSessionContext:
    def __init__(self, db: AsyncMock) -> None:
        self._db = db

    async def __aenter__(self) -> AsyncMock:
        return self._db

    async def __aexit__(self, *_args) -> None:
        return None


@pytest.fixture
def chat_client(api_client: TestClient) -> Generator[tuple[TestClient, AsyncMock], None, None]:
    db = _mock_chat_db()
    with patch("app.api.chat.async_session_factory", lambda: _MockSessionContext(db)):
        yield api_client, db


async def _clarify_stream(*_args, **_kwargs):
    yield {"type": "clarify", "content": "请补充设备型号。", "language": "zh"}


async def _complete_stream(*_args, **_kwargs):
    yield {"type": "citations", "citations": [{"ref": 1, "document_id": "doc-1"}]}
    yield {"type": "delta", "content": "答案"}
    yield {
        "type": "complete",
        "answer": "答案[1]",
        "citations": [{"ref": 1, "document_id": "doc-1"}],
        "embeds": [],
        "language": "zh",
    }


def test_chat_sse_clarify_emits_delta_and_done(chat_client) -> None:
    client, _db = chat_client
    session = type("Session", (), {})()
    session.id = uuid.uuid4()
    session.doc_ids = []

    with (
        patch("app.api.chat.get_agent_service", return_value=MagicMock()),
        patch("app.api.chat._get_or_create_session", AsyncMock(return_value=session)),
        patch("app.api.chat.stream_agent_answer", _clarify_stream),
        patch("app.api.chat.persist_turn", AsyncMock()) as persist_mock,
    ):
        with client.stream("POST", "/api/v1/chat", json={"message": "报警代码"}) as response:
            assert response.status_code == 200
            payloads = [
                json.loads(line[6:])
                for line in response.iter_lines()
                if line.startswith("data: ")
            ]

    assert payloads[0] == {"type": "delta", "content": "请补充设备型号。"}
    assert payloads[1]["type"] == "done"
    assert payloads[1]["session_id"] == str(session.id)
    persist_mock.assert_awaited_once()


def test_chat_sse_complete_persists_turn(chat_client) -> None:
    client, _db = chat_client
    session = type("Session", (), {})()
    session.id = uuid.uuid4()
    session.doc_ids = []

    with (
        patch("app.api.chat.get_agent_service", return_value=MagicMock()),
        patch("app.api.chat._get_or_create_session", AsyncMock(return_value=session)),
        patch("app.api.chat.stream_agent_answer", _complete_stream),
        patch("app.api.chat.persist_turn", AsyncMock()) as persist_mock,
    ):
        with client.stream("POST", "/api/v1/chat", json={"message": "如何复位"}) as response:
            payloads = [
                json.loads(line[6:])
                for line in response.iter_lines()
                if line.startswith("data: ")
            ]

    assert payloads[0]["type"] == "citations"
    assert payloads[1] == {"type": "delta", "content": "答案"}
    assert payloads[2]["type"] == "done"
    assert payloads[2]["content"] == "答案[1]"
    persist_mock.assert_awaited_once()
    assert persist_mock.await_args.args[3] == "答案[1]"
