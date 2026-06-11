def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    top_k: int,
    k: int = 60,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranked_ids in ranked_lists:
        for rank, chunk_id in enumerate(ranked_ids):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)

    fused = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return fused[:top_k]
