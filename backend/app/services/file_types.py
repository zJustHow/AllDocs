from dataclasses import dataclass


@dataclass(frozen=True)
class SupportedFileType:
    extension: str
    content_type: str
    label: str


SUPPORTED_FILE_TYPES: dict[str, SupportedFileType] = {
    ".pdf": SupportedFileType(".pdf", "application/pdf", "PDF"),
    ".docx": SupportedFileType(
        ".docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "Word",
    ),
    ".txt": SupportedFileType(".txt", "text/plain", "Text"),
    ".md": SupportedFileType(".md", "text/markdown", "Text"),
    ".html": SupportedFileType(".html", "text/html", "HTML"),
    ".htm": SupportedFileType(".htm", "text/html", "HTML"),
    ".png": SupportedFileType(".png", "image/png", "Image"),
    ".jpg": SupportedFileType(".jpg", "image/jpeg", "Image"),
    ".jpeg": SupportedFileType(".jpeg", "image/jpeg", "Image"),
    ".webp": SupportedFileType(".webp", "image/webp", "Image"),
}

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
