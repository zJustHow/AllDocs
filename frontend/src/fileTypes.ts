export type PreviewMode = "pdf" | "image" | "text" | "unsupported";

const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "webp"]);
const TEXT_EXTENSIONS = new Set(["txt", "md"]);

export function getPreviewMode(
  filename: string,
  contentType?: string | null,
): PreviewMode {
  const ext = filename.includes(".") ? filename.split(".").pop()?.toLowerCase() ?? "" : "";

  if (contentType?.startsWith("image/") || IMAGE_EXTENSIONS.has(ext)) {
    return "image";
  }
  if (ext === "pdf" || contentType === "application/pdf") {
    return "pdf";
  }
  if (
    TEXT_EXTENSIONS.has(ext) ||
    contentType === "text/plain" ||
    contentType === "text/markdown"
  ) {
    return "text";
  }
  return "unsupported";
}

export const UPLOAD_ACCEPT =
  ".pdf,.docx,.txt,.md,.html,.htm,.png,.jpg,.jpeg,.webp,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown,text/html,image/png,image/jpeg,image/webp";
