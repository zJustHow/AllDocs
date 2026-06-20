"""Format retrieved document chunks for LLM context and agent observations."""

from app.services.chunk_filter import chunk_asset_types


def chunk_figure_numbers(chunk: dict) -> list[str]:
    numbers: list[str] = []
    seen: set[str] = set()
    for asset in chunk.get("assets") or []:
        figure_number = str(asset.get("figure_number") or "").strip()
        if not figure_number or figure_number in seen:
            continue
        seen.add(figure_number)
        numbers.append(figure_number)
    return numbers


def format_score_label(score: object) -> str | None:
    if score is None:
        return None
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None
    # Semantic similarity is 0–1; near-perfect values are not useful in headers.
    if 0.0 <= value <= 1.0 and value >= 0.999:
        return None
    return f"score={value:.3f}"


def format_chunk_header(
    item: dict,
    *,
    index: int | None = None,
    indent: str = "",
    detailed: bool = False,
) -> str:
    label = f"[{index}]" if index is not None else ""
    header = f"{indent}{label} {item.get('document_name', '')}".strip()
    page = item.get("page")
    if page is not None:
        header += f" p.{page}"
    if item.get("section"):
        header += f" §{item.get('section')}"
    asset_types = chunk_asset_types(item)
    if asset_types:
        header += f" assets={','.join(asset_types)}"
    if detailed:
        figure_numbers = chunk_figure_numbers(item)
        if figure_numbers:
            header += f" fig={','.join(figure_numbers)}"
        if item.get("assets"):
            header += " visual=1"
        if item.get("caption") or any(
            asset.get("caption")
            or asset.get("figure_caption")
            or asset.get("vlm_caption")
            for asset in item.get("assets") or []
        ):
            header += " caption=1"
        score_label = format_score_label(item.get("score"))
        if score_label:
            header += f" {score_label}"
        chunk_id = item.get("chunk_id")
        if chunk_id:
            header += f" id={chunk_id}"
        chunk_index = item.get("chunk_index")
        if chunk_index is not None:
            header += f" idx={chunk_index}"
    elif item.get("assets"):
        header += " (visual)"
    return header
