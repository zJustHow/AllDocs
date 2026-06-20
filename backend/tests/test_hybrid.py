from app.services.hybrid import reciprocal_rank_fusion


def test_reciprocal_rank_fusion_merges_overlapping_lists() -> None:
    fused = reciprocal_rank_fusion(
        [["a", "b", "c"], ["b", "d", "a"]],
        top_k=3,
        k=60,
    )

    ids = [chunk_id for chunk_id, _ in fused]
    assert ids[0] in {"a", "b"}
    assert set(ids) == {"a", "b", "d"}


def test_reciprocal_rank_fusion_respects_top_k() -> None:
    fused = reciprocal_rank_fusion([list("abcdef")], top_k=2, k=10)
    assert len(fused) == 2
