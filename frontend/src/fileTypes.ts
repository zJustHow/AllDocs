import {
  buildFallbackPreviewModes,
  buildFallbackUploadAccept,
  type PreviewMode,
} from "./shared/contract";

let uploadAccept = buildFallbackUploadAccept();
let previewModes = buildFallbackPreviewModes();

export async function loadSupportedFormats(): Promise<void> {
  try {
    const res = await fetch("/api/v1/documents/formats");
    if (!res.ok) return;
    const data = (await res.json()) as {
      upload_accept?: string;
      preview_modes?: Record<string, PreviewMode>;
    };
    if (data.upload_accept) {
      uploadAccept = data.upload_accept;
    }
    if (data.preview_modes) {
      previewModes = data.preview_modes;
    }
  } catch {
    // Keep fallback values when API is unavailable.
  }
}

export function getUploadAccept(): string {
  return uploadAccept;
}

export function getPreviewMode(
  filename: string,
  contentType?: string | null,
): PreviewMode {
  const ext = filename.includes(".")
    ? `.${filename.split(".").pop()?.toLowerCase() ?? ""}`
    : "";

  if (contentType?.startsWith("image/") || previewModes[ext] === "image") {
    return "image";
  }
  if (ext === ".pdf" || contentType === "application/pdf") {
    return "pdf";
  }
  if (
    previewModes[ext] === "text" ||
    contentType === "text/plain" ||
    contentType === "text/markdown"
  ) {
    return "text";
  }
  return previewModes[ext] ?? "unsupported";
}

export type { PreviewMode };
