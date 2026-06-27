import asyncio
import base64
import json
import re
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jwt.exceptions import InvalidTokenError

from app.api.schemas import ChunkFilter
from app.config import get_settings
from app.db.models import User
from app.db.session import async_session_factory
from app.services.agent.answer_flow import persist_turn, stream_agent_answer
from app.services.auth_service import get_user_by_id
from app.services.auth_tokens import decode_access_token
from app.services.chat_sessions import get_or_create_chat_session, load_recent_chat_history
from app.services.citations_util import strip_inline_citation_markers
from app.services.deps import get_agent_service
from app.services.rag import detect_language
from app.services.speech import SpeechService, is_whisper_ready, wait_whisper_ready

router = APIRouter(tags=["voice-ws"])

_WHISPER_READY_TIMEOUT = 300.0
_TRANSCRIBE_TIMEOUT = 120.0

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？.!?])\s*")


def _split_sentences(text: str) -> tuple[list[str], str]:
    if not text:
        return [], ""
    parts = _SENTENCE_SPLIT.split(text)
    if len(parts) == 1:
        return [], text
    complete = [part for part in parts[:-1] if part.strip()]
    return complete, parts[-1]


async def _send_json(websocket: WebSocket, payload: dict) -> None:
    await websocket.send_text(json.dumps(payload, ensure_ascii=False))


async def _synthesize_sentence(
    websocket: WebSocket,
    speech: SpeechService,
    sentence: str,
    lang: str,
) -> None:
    spoken = strip_inline_citation_markers(sentence)
    if not spoken:
        return
    await _send_json(websocket, {"type": "status", "stage": "speaking"})
    audio_wav = await asyncio.to_thread(speech.synthesize, spoken, lang)
    await _send_json(
        websocket,
        {"type": "audio", "data": base64.b64encode(audio_wav).decode("ascii")},
    )


async def _authenticate_voice_socket(websocket: WebSocket) -> User | None:
    settings = get_settings()
    if settings.auth_disabled:
        from app.api.auth_deps import _dev_user

        return _dev_user()

    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(str(payload["sub"]))
    except (InvalidTokenError, ValueError, KeyError):
        return None

    async with async_session_factory() as db:
        user = await get_user_by_id(db, user_id)
        if not user or not user.is_active:
            return None
    return user


@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket) -> None:
    user = await _authenticate_voice_socket(websocket)
    if not user:
        await websocket.close(code=4401, reason="Unauthorized")
        return
    await websocket.accept()
    speech = SpeechService()
    settings = get_settings()
    agent = get_agent_service()

    try:
        while True:
            raw = await websocket.receive_text()
            payload = json.loads(raw)
            msg_type = payload.get("type")

            if msg_type == "ping":
                await _send_json(websocket, {"type": "pong"})
                continue

            if msg_type != "audio":
                await _send_json(websocket, {"type": "error", "message": "Unsupported message type"})
                continue

            audio_b64 = payload.get("data", "")
            if not audio_b64:
                await _send_json(websocket, {"type": "error", "message": "Empty audio"})
                continue

            session_id_raw = payload.get("session_id")
            doc_ids_raw = payload.get("doc_ids", [])
            filters_raw = payload.get("filters")
            with_audio = payload.get("with_audio", True)
            mime_type = payload.get("mime_type")
            language_hint = payload.get("language")

            if not is_whisper_ready():
                await _send_json(websocket, {"type": "status", "stage": "model_loading"})
                ready = await asyncio.to_thread(
                    wait_whisper_ready,
                    _WHISPER_READY_TIMEOUT,
                )
                if not ready:
                    await _send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Speech model is still loading. Please try again shortly.",
                        },
                    )
                    continue

            await _send_json(websocket, {"type": "status", "stage": "transcribing"})

            audio_bytes = base64.b64decode(audio_b64)
            try:
                transcription = await asyncio.wait_for(
                    asyncio.to_thread(
                        speech.transcribe,
                        audio_bytes,
                        str(language_hint) if language_hint else None,
                        str(mime_type) if mime_type else None,
                    ),
                    timeout=_TRANSCRIBE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                await _send_json(
                    websocket,
                    {"type": "error", "message": "Transcription timed out"},
                )
                continue
            question = transcription["text"].strip()
            if not question:
                await _send_json(websocket, {"type": "error", "message": "Could not transcribe audio"})
                continue

            lang = transcription.get("language") or detect_language(question)
            await _send_json(
                websocket,
                {"type": "transcript", "text": question, "language": lang},
            )
            await _send_json(websocket, {"type": "status", "stage": "retrieving"})

            parsed_doc_ids = [uuid.UUID(str(item)) for item in doc_ids_raw]
            chunk_filters = ChunkFilter.model_validate(filters_raw) if filters_raw else None

            async with async_session_factory() as db:
                session, effective_doc_ids = await get_or_create_chat_session(
                    db,
                    user=user,
                    session_id=uuid.UUID(str(session_id_raw)) if session_id_raw else None,
                    requested_doc_ids=parsed_doc_ids,
                )
                await db.commit()
                session_id = session.id
                history = await load_recent_chat_history(db, session_id)

            async def on_agent_step(event: dict) -> None:
                await _send_json(websocket, event)

            pending_tts = ""
            answering_sent = False

            async for event in stream_agent_answer(
                agent,
                question,
                effective_doc_ids or None,
                chunk_filters,
                history,
                settings,
                lang,
                on_agent_step=on_agent_step,
            ):
                event_type = event["type"]

                if event_type == "clarify":
                    content = event["content"]
                    await _send_json(websocket, {"type": "answer_delta", "content": content})
                    if with_audio:
                        await _synthesize_sentence(websocket, speech, content, lang)
                    async with async_session_factory() as persist_db:
                        await persist_turn(persist_db, session_id, question, content, [])
                    await _send_json(
                        websocket,
                        {
                            "type": "done",
                            "session_id": str(session_id),
                            "citations": [],
                            "language": lang,
                        },
                    )
                    break

                if event_type == "fallback":
                    content = event["content"]
                    await _send_json(websocket, {"type": "answer_delta", "content": content})
                    if with_audio:
                        await _synthesize_sentence(websocket, speech, content, lang)
                    async with async_session_factory() as persist_db:
                        await persist_turn(persist_db, session_id, question, content, [])
                    await _send_json(
                        websocket,
                        {
                            "type": "done",
                            "session_id": str(session_id),
                            "citations": [],
                            "language": lang,
                        },
                    )
                    break

                if event_type == "citations":
                    await _send_json(websocket, event)
                    continue

                if event_type == "delta":
                    if not answering_sent:
                        await _send_json(websocket, {"type": "status", "stage": "answering"})
                        answering_sent = True
                    delta = event["content"]
                    await _send_json(websocket, {"type": "answer_delta", "content": delta})
                    if with_audio:
                        pending_tts += delta
                        complete, pending_tts = _split_sentences(pending_tts)
                        for sentence in complete:
                            await _synthesize_sentence(websocket, speech, sentence, lang)
                    continue

                if event_type == "embeds":
                    await _send_json(websocket, event)
                    continue

                if event_type == "complete":
                    if with_audio and pending_tts.strip():
                        await _synthesize_sentence(websocket, speech, pending_tts.strip(), lang)
                    async with async_session_factory() as persist_db:
                        await persist_turn(
                            persist_db,
                            session_id,
                            question,
                            event["answer"],
                            event["citations"],
                            event["embeds"],
                        )
                    await _send_json(
                        websocket,
                        {
                            "type": "done",
                            "session_id": str(session_id),
                            "content": event["answer"],
                            "citations": event["citations"],
                            "embeds": event["embeds"],
                            "language": lang,
                        },
                    )
                    break

                await _send_json(websocket, event)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await _send_json(websocket, {"type": "error", "message": str(exc)})
        except Exception:
            return
