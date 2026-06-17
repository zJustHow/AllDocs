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
    inlineCitationRef: string;
    inlineCitationMarker: string;
    embedMarker: string;
    embedMarkerLoose: string;
    messageToken: string;
  };
  embed: {
    markerTemplate: string;
    bboxRoundDecimals: number;
  };
};

const fileFormats = fileFormatsContract as { types: FileFormatEntry[] };

export const inlineCitationMarkerSource = markers.regex.inlineCitationMarker;
export const embedMarkerLooseSource = markers.regex.embedMarkerLoose;

export const inlineCitationRefPattern = new RegExp(
  markers.regex.inlineCitationRef,
  "g",
);
export const inlineCitationMarkerPattern = new RegExp(
  markers.regex.inlineCitationMarker,
  "g",
);
export const embedMarkerPattern = new RegExp(markers.regex.embedMarker, "g");
export const embedMarkerLoosePattern = new RegExp(
  markers.regex.embedMarkerLoose,
  "g",
);
export const messageTokenPattern = new RegExp(
  markers.regex.messageToken,
  "g",
);

export function formatEmbedMarker(ref: number): string {
  return markers.embed.markerTemplate.replace("{ref}", String(ref));
}

export function stripInlineMarkers(content: string): string {
  return content
    .replace(inlineCitationMarkerPattern, "")
    .replace(embedMarkerLoosePattern, "");
}

function normalizedBboxKey(bbox?: number[] | null): string | null {
  if (!bbox || bbox.length !== 4) return null;
  const factor = 10 ** markers.embed.bboxRoundDecimals;
  return bbox.map((value) => Math.round(value * factor) / factor).join(",");
}

export function embedDedupeKey(embed: MessageEmbed): string {
  if (embed.asset_id) {
    return `asset:${embed.asset_id}`;
  }
  const bboxKey = normalizedBboxKey(embed.bbox);
  if (embed.type === "figure") {
    if (bboxKey) {
      return `figure:${embed.document_id}:${embed.page}:${bboxKey}`;
    }
    return `figure:${embed.document_id}:${embed.page}`;
  }
  if (embed.type === "table" && bboxKey) {
    return `table:${embed.document_id}:${embed.page}:${bboxKey}`;
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
