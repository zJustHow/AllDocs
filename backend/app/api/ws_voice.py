import asyncio
import base64
import json
import re
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.api.schemas import ChunkFilter
from app.db.models import Message, Session
from app.db.session import async_session_factory
from app.services.citations_util import finalize_answer_citations, public_citations
from app.services.rag import RAGService, detect_language
from app.services.speech import SpeechService

router = APIRouter(tags=["voice-ws"])

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？.!?])\s*")
_CITATION_MARKER = re.compile(r"\[\d+\]")


def _strip_citation_markers(text: str) -> str:
    return _CITATION_MARKER.sub("", text).strip()


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


@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    speech = SpeechService()
    rag = RAGService()

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

            await _send_json(websocket, {"type": "status", "stage": "transcribing"})

            audio_bytes = base64.b64decode(audio_b64)
            transcription = await asyncio.to_thread(speech.transcribe, audio_bytes)
            question = transcription["text"].strip()
            if not question:
                await _send_json(websocket, {"type": "error", "message": "Could not transcribe audio"})
                continue

            lang = transcription.get("language") or detect_language(question)
            await _send_json(
                websocket,
                {"type": "transcript", "text": question, "language": lang},
            )

            parsed_doc_ids = [uuid.UUID(str(item)) for item in doc_ids_raw]
            chunk_filters = ChunkFilter.model_validate(filters_raw) if filters_raw else None

            async with async_session_factory() as db:
                if session_id_raw:
                    session = await db.get(Session, uuid.UUID(str(session_id_raw)))
                    if not session:
                        await _send_json(websocket, {"type": "error", "message": "Session not found"})
                        continue
                else:
                    session = Session(doc_ids=[str(doc_id) for doc_id in parsed_doc_ids])
                    db.add(session)
                    await db.flush()
                    await db.commit()

                history_result = await db.execute(
                    select(Message).where(Message.session_id == session.id).order_by(Message.created_at)
                )
                history = [
                    {"role": message.role, "content": message.content}
                    for message in history_result.scalars().all()
                ]

                effective_doc_ids = parsed_doc_ids or [uuid.UUID(doc_id) for doc_id in session.doc_ids]
                citations = await rag.retrieve(
                    db, question, effective_doc_ids or None, chunk_filters
                )

                if not citations:
                    fallback = "Not found in the manual." if lang == "en" else "说明书中未找到相关信息。"
                    await _send_json(websocket, {"type": "answer_delta", "content": fallback})
                    if with_audio:
                        audio_wav = await asyncio.to_thread(speech.synthesize, fallback, lang)
                        await _send_json(
                            websocket,
                            {"type": "audio", "data": base64.b64encode(audio_wav).decode("ascii")},
                        )
                    db.add(Message(session_id=session.id, role="user", content=question))
                    db.add(
                        Message(
                            session_id=session.id,
                            role="assistant",
                            content=fallback,
                            citations=[],
                        )
                    )
                    await db.commit()
                    await _send_json(
                        websocket,
                        {
                            "type": "done",
                            "session_id": str(session.id),
                            "citations": [],
                            "language": lang,
                        },
                    )
                    continue

                context = rag.build_context(citations)
                refs = public_citations(citations)
                await _send_json(websocket, {"type": "citations", "citations": refs})
                answer_parts: list[str] = []
                pending_tts = ""

                await _send_json(websocket, {"type": "status", "stage": "answering"})

                async for delta in rag.llm.chat_stream(question, context, history):
                    answer_parts.append(delta)
                    pending_tts += delta
                    await _send_json(websocket, {"type": "answer_delta", "content": delta})

                    if with_audio:
                        complete, pending_tts = _split_sentences(pending_tts)
                        for sentence in complete:
                            spoken = _strip_citation_markers(sentence)
                            if not spoken:
                                continue
                            await _send_json(websocket, {"type": "status", "stage": "speaking"})
                            audio_wav = await asyncio.to_thread(speech.synthesize, spoken, lang)
                            await _send_json(
                                websocket,
                                {"type": "audio", "data": base64.b64encode(audio_wav).decode("ascii")},
                            )

                if with_audio and pending_tts.strip():
                    spoken = _strip_citation_markers(pending_tts.strip())
                    if spoken:
                        await _send_json(websocket, {"type": "status", "stage": "speaking"})
                        audio_wav = await asyncio.to_thread(speech.synthesize, spoken, lang)
                        await _send_json(
                            websocket,
                            {"type": "audio", "data": base64.b64encode(audio_wav).decode("ascii")},
                        )

                answer, refs = finalize_answer_citations("".join(answer_parts), citations)

                db.add(Message(session_id=session.id, role="user", content=question))
                db.add(
                    Message(
                        session_id=session.id,
                        role="assistant",
                        content=answer,
                        citations=refs,
                    )
                )
                await db.commit()

                await _send_json(
                    websocket,
                    {
                        "type": "done",
                        "session_id": str(session.id),
                        "content": answer,
                        "citations": refs,
                        "language": lang,
                    },
                )
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await _send_json(websocket, {"type": "error", "message": str(exc)})
        except Exception:
            return
