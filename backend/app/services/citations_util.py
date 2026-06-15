import re

TRAILING_SOURCES_SECTION = re.compile(
    r"\n+(?:#{1,3}\s*)?(?:来源|引用|References|Sources)\s*[:：]?\s*\n[\s\S]*$",
    re.IGNORECASE,
)


def normalize_answer_citations(answer: str) -> str:
    """Keep inline [n] markers and drop trailing source-list sections."""
    return TRAILING_SOURCES_SECTION.sub("", answer).strip()


def public_citations(citations: list[dict]) -> list[dict]:
    return [
        {
            "document_id": item["document_id"],
            "document_name": item["document_name"],
            "page": item["page"],
            "section": item["section"],
            "snippet": item["snippet"],
            "score": item["score"],
        }
        for item in citations
    ]
