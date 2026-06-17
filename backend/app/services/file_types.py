from dataclasses import dataclass

from app.services.shared_contract import load_file_formats


@dataclass(frozen=True)
class SupportedFileType:
    extension: str
    content_type: str
    label: str
    preview_mode: str


def _build_supported_file_types() -> dict[str, SupportedFileType]:
    payload = load_file_formats()
    return {
        item["extension"]: SupportedFileType(
            extension=item["extension"],
            content_type=item["contentType"],
            label=item["label"],
            preview_mode=item["previewMode"],
        )
        for item in payload["types"]
    }


SUPPORTED_FILE_TYPES: dict[str, SupportedFileType] = _build_supported_file_types()
SUPPORTED_EXTENSIONS = tuple(SUPPORTED_FILE_TYPES.keys())


def get_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def detect_file_type(filename: str) -> SupportedFileType | None:
    return SUPPORTED_FILE_TYPES.get(get_extension(filename))


def is_supported_filename(filename: str) -> bool:
    return detect_file_type(filename) is not None


def resolve_content_type(filename: str, uploaded: str | None = None) -> str:
    detected = detect_file_type(filename)
    if uploaded and uploaded not in {"", "application/octet-stream"}:
        return uploaded
    if detected:
        return detected.content_type
    return "application/octet-stream"


def supported_formats_label() -> str:
    return ", ".join(ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS)


def preview_mode(filename: str, content_type: str | None = None) -> str:
    ext = get_extension(filename)
    detected = detect_file_type(filename)

    if content_type and content_type.startswith("image/"):
        return "image"
    if ext == ".pdf" or content_type == "application/pdf":
        return "pdf"
    if content_type in {"text/plain", "text/markdown"}:
        return "text"
    if detected:
        return detected.preview_mode
    return "unsupported"


def upload_accept() -> str:
    content_types = sorted({item.content_type for item in SUPPORTED_FILE_TYPES.values()})
    return ",".join([*SUPPORTED_EXTENSIONS, *content_types])


def supported_formats_payload() -> dict:
    return {
        "extensions": list(SUPPORTED_EXTENSIONS),
        "upload_accept": upload_accept(),
        "labels": supported_formats_label(),
        "preview_modes": {
            ext: item.preview_mode for ext, item in SUPPORTED_FILE_TYPES.items()
        },
    }
