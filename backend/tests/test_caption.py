from app.services.caption import _parse_vision_json


def test_parse_vision_json_table():
    result = _parse_vision_json(
        '{"kind":"table","caption":"参数规格表，含电压与电流列。"}'
    )
    assert result is not None
    assert result.kind == "table"
    assert "参数" in result.caption


def test_parse_vision_json_figure_from_markdown_fence():
    result = _parse_vision_json('说明：{"kind":"diagram","caption":"接线示意图。"}')
    assert result is not None
    assert result.kind == "diagram"
    assert result.caption == "接线示意图。"


def test_parse_vision_json_invalid():
    assert _parse_vision_json("not json") is None
