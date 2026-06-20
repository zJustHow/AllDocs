from app.services.asset_lookup import parse_asset_number


def test_parse_asset_number_normalizes_common_formats() -> None:
    assert parse_asset_number("4-7") == "4-7"
    assert parse_asset_number("图 4-7") == "4-7"
    assert parse_asset_number("表2-1") == "2-1"
    assert parse_asset_number("Figure 4-7") == "4-7"
    assert parse_asset_number("Table 2-1") == "2-1"


def test_parse_asset_number_rejects_invalid_input() -> None:
    assert parse_asset_number("") is None
    assert parse_asset_number("报警代码 E001") is None
