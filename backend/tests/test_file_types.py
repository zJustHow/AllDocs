from app.services.file_types import (
    get_extension,
    is_supported_filename,
    resolve_content_type,
    supported_formats_label,
)


def test_get_extension_is_case_insensitive() -> None:
    assert get_extension("Manual.PDF") == ".pdf"
    assert get_extension("notes") == ""


def test_is_supported_filename_accepts_known_types() -> None:
    assert is_supported_filename("guide.pdf") is True
    assert is_supported_filename("guide.exe") is False


def test_resolve_content_type_prefers_detected_type() -> None:
    assert resolve_content_type("guide.pdf", "application/octet-stream") == "application/pdf"
    assert resolve_content_type("guide.pdf", "application/pdf") == "application/pdf"


def test_supported_formats_label_lists_extensions() -> None:
    label = supported_formats_label()
    assert "pdf" in label
