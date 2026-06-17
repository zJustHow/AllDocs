import type { Citation, MessageEmbed } from "./types";

export interface ViewerTarget {
  documentId: string;
  documentName: string;
  contentType?: string | null;
  page: number | null;
  section: string | null;
  snippet?: string;
  pageCount?: number | null;
}

export function getCitationIndex(
  citation: Citation,
  citations: Citation[],
): number {
  return citations.findIndex(
    (item) =>
      item.document_id === citation.document_id &&
      item.page === citation.page &&
      item.section === citation.section,
  );
}

const INLINE_CITATION_MARKER = /\[\s*\d+\s*\]|【\s*\d+\s*】/g;
const INLINE_EMBED_MARKER = /\{\{embed:\s*\d+\s*\}\}/g;

export function stripInlineCitationMarkers(content: string): string {
  return content
    .replace(INLINE_CITATION_MARKER, "")
    .replace(INLINE_EMBED_MARKER, "");
}

export function formatCitationLabel(index: number): string {
  return `[${index + 1}]`;
}

export function formatDocumentNameLabel(name: string, maxLength = 16): string {
  const trimmed = name.trim();
  if (trimmed.length <= maxLength) return trimmed;
  return `${trimmed.slice(0, maxLength - 1)}…`;
}

export function formatCitationBadgeName(
  citation: Citation,
  citations: Citation[],
  maxLength = 16,
): string {
  const index = getCitationIndex(citation, citations);
  if (index < 0) {
    return formatDocumentNameLabel(citation.document_name, maxLength);
  }
  const suffix = ` ${formatCitationLabel(index)}`;
  const nameMax = Math.max(4, maxLength - suffix.length);
  return formatDocumentNameLabel(citation.document_name, nameMax);
}

export function formatCitationBadgeIndex(
  citation: Citation,
  citations: Citation[],
): string {
  const index = getCitationIndex(citation, citations);
  return index >= 0 ? formatCitationLabel(index) : "";
}

export interface MessageContentSection {
  content: string;
  citations: Citation[];
}

export function citationKey(citation: Citation): string {
  return `${citation.document_id}:${citation.page}:${citation.section}`;
}

const EMBED_ONLY_PARAGRAPH = /^\s*\{\{embed:\s*\d+\s*\}\}\s*$/;

export function splitContentIntoSections(content: string): string[] {
  const trimmed = content.trim();
  if (!trimmed) return [];

  if (/^#{1,6}\s/m.test(trimmed)) {
    return trimmed.split(/(?=^#{1,6}\s)/m).filter((part) => part.trim());
  }

  // Keep embed markers in the same flow as nearby text so images can float beside prose.
  if (/\{\{embed:\s*\d+\s*\}\}/.test(trimmed)) {
    return [trimmed];
  }

  const paragraphs = trimmed.split(/\n{2,}/).filter((part) => part.trim());
  const merged: string[] = [];

  for (let index = 0; index < paragraphs.length; index += 1) {
    const part = paragraphs[index];
    if (EMBED_ONLY_PARAGRAPH.test(part) && index + 1 < paragraphs.length) {
      merged.push(`${part}\n\n${paragraphs[index + 1]}`);
      index += 1;
      continue;
    }
    merged.push(part);
  }

  return merged.length > 0 ? merged : [trimmed];
}

export function extractSectionCitations(
  content: string,
  citations: Citation[],
  embeds: MessageEmbed[] = [],
): MessageContentSection {
  const segments = splitMessageWithCitations(content, citations, { embeds });
  const sectionCitations: Citation[] = [];
  const seen = new Set<string>();
  const textParts: string[] = [];

  for (const segment of segments) {
    if (segment.type === "text" || segment.type === "embed") {
      textParts.push(segment.value);
      continue;
    }

    const key = citationKey(segment.citation);
    if (!seen.has(key)) {
      seen.add(key);
      sectionCitations.push(segment.citation);
    }
  }

  return {
    content: textParts.join(""),
    citations: sectionCitations,
  };
}

export function groupContentIntoSections(
  content: string,
  citations: Citation[],
  embeds: MessageEmbed[] = [],
): MessageContentSection[] {
  return splitContentIntoSections(content).map((part) =>
    extractSectionCitations(part, citations, embeds),
  );
}

export function citationToViewerTarget(citation: Citation): ViewerTarget {
  return {
    documentId: citation.document_id,
    documentName: citation.document_name,
    page: citation.page,
    section: citation.section,
    snippet: citation.snippet,
  };
}

function parseInlineCitationRef(
  inner: string,
  citations: Citation[],
): Citation | null {
  const numericRefs = inner.match(/\d+/g);
  if (numericRefs?.length === 1 && /^\s*\d+\s*$/.test(inner)) {
    const index = Number(numericRefs[0]) - 1;
    return citations[index] ?? null;
  }

  const indexMatch = inner.match(/^\[?(\d+)\]?$/);
  if (indexMatch) {
    const index = Number(indexMatch[1]) - 1;
    return citations[index] ?? null;
  }

  const pageMatch = inner.match(/p\.(\d+)/i);
  const sectionMatch = inner.match(/§\s*(.+)$/);
  const page = pageMatch ? Number(pageMatch[1]) : null;
  const section = sectionMatch ? sectionMatch[1].trim() : null;
  const docName = inner
    .replace(/\s*p\.\d+/i, "")
    .replace(/\s*§\s*.+$/, "")
    .trim();

  const exact = citations.find((citation) => {
    if (citation.document_name !== docName) return false;
    if (page !== null && citation.page !== page) return false;
    if (section && citation.section !== section) return false;
    return true;
  });
  if (exact) return exact;

  const byName = citations.find(
    (citation) =>
      citation.document_name.includes(docName) ||
      docName.includes(citation.document_name),
  );
  if (byName) return byName;

  if (page !== null) {
    return citations.find((citation) => citation.page === page) ?? null;
  }

  return null;
}

export type MessageSegment =
  | { type: "text"; value: string }
  | { type: "citation"; value: string; citation: Citation }
  | { type: "embed"; value: string; embed: MessageEmbed };

function findEmbed(ref: number, embeds: MessageEmbed[]): MessageEmbed | null {
  return embeds.find((item) => item.ref === ref) ?? null;
}

export function embedDedupeKey(embed: MessageEmbed): string {
  if (embed.asset_id) {
    return `asset:${embed.asset_id}`;
  }
  return `page:${embed.document_id}:${embed.page}`;
}

export function splitMessageWithCitations(
  content: string,
  citations: Citation[],
  options?: { hideUnmatched?: boolean; embeds?: MessageEmbed[] },
): MessageSegment[] {
  const hideUnmatched = options?.hideUnmatched ?? false;
  const embeds = options?.embeds ?? [];
  const pattern =
    /\{\{embed:\s*(\d+)\s*\}\}|\[\s*(\d+)\s*\]|【\s*(\d+)\s*】|\[([^\]]+)\]/g;

  if (!citations.length && !embeds.length) {
    return [{ type: "text", value: stripInlineCitationMarkers(content) }];
  }

  const segments: MessageSegment[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(content)) !== null) {
    if (match.index > lastIndex) {
      segments.push({
        type: "text",
        value: content.slice(lastIndex, match.index),
      });
    }

    const embedRef = match[1];
    if (embedRef) {
      const embed = findEmbed(Number(embedRef), embeds);
      if (embed) {
        segments.push({ type: "embed", value: match[0], embed });
      } else if (!hideUnmatched) {
        segments.push({ type: "text", value: match[0] });
      }
      lastIndex = match.index + match[0].length;
      continue;
    }

    const numericRef = match[2] ?? match[3];
    if (numericRef) {
      const index = Number(numericRef) - 1;
      const citation = citations[index];
      if (citation) {
        segments.push({ type: "citation", value: match[0], citation });
      } else if (!hideUnmatched) {
        segments.push({ type: "text", value: match[0] });
      }
    } else {
      const inner = match[4];
      const citation = parseInlineCitationRef(inner, citations);
      if (citation) {
        segments.push({ type: "citation", value: match[0], citation });
      } else if (!hideUnmatched) {
        segments.push({ type: "text", value: match[0] });
      }
    }
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < content.length) {
    segments.push({ type: "text", value: content.slice(lastIndex) });
  }

  return segments.length ? segments : [{ type: "text", value: content }];
}
