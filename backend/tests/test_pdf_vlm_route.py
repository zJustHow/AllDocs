from app.services.pdf_vlm_route import _looks_like_table_caption


def test_table_caption_heuristic():
    assert _looks_like_table_caption("表 3-1 主要参数")
    assert not _looks_like_table_caption("图 3-1 系统框图")
    assert not _looks_like_table_caption(None)
