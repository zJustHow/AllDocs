from app.services.citations_util import (
    public_citations,
    renumber_answer_citations,
    strip_inline_citation_markers,
)


def _chunk(document_id: str, name: str, page: int) -> dict:
    return {
        "document_id": document_id,
        "document_name": name,
        "page": page,
        "section": "Alarm",
        "snippet": f"snippet-{page}",
        "score": 0.9,
        "layout_regions": [{"page": page, "bbox": [0.0, 0.0, 10.0, 10.0]}],
    }


def test_renumber_answer_citations_follows_first_appearance() -> None:
    chunks = [_chunk("d1", "Manual", 1), _chunk("d2", "Manual", 2)]
    answer, cited, old_to_new = renumber_answer_citations(
        "先看[2]，再看[1]。",
        chunks,
    )

    assert old_to_new == {2: 1, 1: 2}
    assert len(cited) == 2
    assert cited[0]["page"] == 2
    assert "[1]" in answer and "[2]" in answer


def test_renumber_answer_citations_ignores_out_of_range_refs() -> None:
    answer, cited, mapping = renumber_answer_citations("无效引用[9]", [_chunk("d1", "Manual", 1)])

    assert answer == "无效引用[9]"
    assert cited == []
    assert mapping == {}


def test_strip_inline_citation_markers_removes_bracket_refs() -> None:
    assert strip_inline_citation_markers("步骤完成[1][2]。") == "步骤完成。"


def test_public_citations_normalizes_regions() -> None:
    citations = public_citations(
        [
            {
                "document_id": "doc-1",
                "document_name": "Manual",
                "page": 3,
                "section": "Setup",
                "snippet": "hello",
                "score": 0.8,
                "layout_regions": [{"page": 3, "bbox": [1.0, 2.0, 3.0, 4.0]}],
            }
        ]
    )

    assert citations[0]["regions"] == [{"page": 3, "bbox": [1.0, 2.0, 3.0, 4.0]}]
    assert "bbox" not in citations[0]
