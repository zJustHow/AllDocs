import os
import tempfile

from app.config import Settings
from app.services.rag import (
    RAGService,
    detect_language,
    low_relevance_message,
    model_path_ready,
    not_found_message,
    resolve_retrieval_fallback,
)


def test_model_path_ready_for_relative_and_absolute_paths() -> None:
    assert model_path_ready("BAAI/bge-m3") is True

    with tempfile.TemporaryDirectory() as tmp:
        missing = os.path.join(tmp, "missing-model")
        assert model_path_ready(missing) is False

        ready = os.path.join(tmp, "ready-model")
        os.makedirs(ready)
        with open(os.path.join(ready, "config.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        assert model_path_ready(ready) is True


def test_detect_language_zh_and_en() -> None:
    assert detect_language("机器人零点标定步骤") == "zh"
    assert detect_language("Check TCP settings on the teach pendant.") == "en"


def test_user_messages_for_zh_and_en() -> None:
    assert "操作指南" in not_found_message("zh")
    assert "Not found" in not_found_message("en")
    assert "相关性" in low_relevance_message("zh")
    assert "relevant" in low_relevance_message("en")


def test_resolve_retrieval_fallback_low_relevance() -> None:
    settings = Settings(rag_min_retrieval_score=0.5, rag_min_rerank_score=0.3)
    evidence = [
        {"from_semantic_search": True, "score": 0.2},
        {"from_semantic_search": True, "score": 0.1},
    ]

    message = resolve_retrieval_fallback("zh", evidence=evidence, settings=settings)
    assert message == low_relevance_message("zh")


def test_resolve_retrieval_fallback_not_found_without_evidence() -> None:
    settings = Settings()
    message = resolve_retrieval_fallback("en", evidence=[], settings=settings)
    assert message == not_found_message("en")


def test_resolve_retrieval_fallback_none_when_scores_are_high_enough() -> None:
    settings = Settings(rag_min_retrieval_score=0.4)
    evidence = [{"from_semantic_search": True, "score": 0.9}]

    assert resolve_retrieval_fallback("zh", evidence=evidence, settings=settings) is None


def test_build_context_formats_headers_and_visual_marker() -> None:
    chunks = [
        {
            "document_name": "Manual.pdf",
            "page": 3,
            "section": "Servo",
            "text": "Press the start key.",
            "assets": [{"type": "figure", "asset_id": "a1"}],
        },
        {
            "document_name": "Manual.pdf",
            "page": 4,
            "section": None,
            "text": "Second chunk body.",
            "assets": [],
        },
    ]

    rag = RAGService.__new__(RAGService)
    context = rag.build_context(chunks)

    assert "[1] Manual.pdf p.3 §Servo assets=figure (visual)" in context
    assert "Press the start key." in context
    assert "[2] Manual.pdf p.4" in context
    assert "Second chunk body." in context
    assert "<!-- chunk -->" in context
