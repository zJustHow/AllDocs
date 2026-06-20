import markersContract from "@shared/markers.json";
import fileFormatsContract from "@shared/file_formats.json";
import type { MessageEmbed } from "../types";

type PreviewMode = "pdf" | "image" | "text" | "unsupported";

interface FileFormatEntry {
  extension: string;
  contentType: string;
  label: string;
  previewMode: PreviewMode;
}

const markers = markersContract as {
  regex: {
    inlineCitationMarker: string;
    embedMarkerLoose: string;
    messageToken: string;
  };
};

const fileFormats = fileFormatsContract as { types: FileFormatEntry[] };

export const inlineCitationMarkerPattern = new RegExp(
  markers.regex.inlineCitationMarker,
  "g",
);
export const embedMarkerLoosePattern = new RegExp(
  markers.regex.embedMarkerLoose,
  "g",
);
export const messageTokenPattern = new RegExp(
  markers.regex.messageToken,
  "g",
);

export function stripInlineMarkers(content: string): string {
  return content
    .replace(inlineCitationMarkerPattern, "")
    .replace(embedMarkerLoosePattern, "");
}

export function embedDedupeKey(embed: MessageEmbed): string {
  if (embed.content_hash) {
    return `hash:${embed.content_hash}`;
  }
  if (embed.asset_id) {
    return `asset:${embed.asset_id}`;
  }
  if (embed.url) {
    return `url:${embed.url}`;
  }
  return `page:${embed.document_id}:${embed.page}`;
}

export function buildFallbackUploadAccept(): string {
  const extensions = fileFormats.types.map((item) => item.extension);
  const contentTypes = [
    ...new Set(fileFormats.types.map((item) => item.contentType)),
  ].sort();
  return [...extensions, ...contentTypes].join(",");
}

export function buildFallbackPreviewModes(): Record<string, PreviewMode> {
  return Object.fromEntries(
    fileFormats.types.map((item) => [item.extension, item.previewMode]),
  );
}

export type { PreviewMode };
