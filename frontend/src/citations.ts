import type { Citation, MessageEmbed } from "./types";

export interface ViewerTarget {
  documentId: string;
  documentName: string;
  contentType?: string | null;
  page: number | null;
  section: string | null;
  snippet?: string;
  pageCount?: number | null;
  bbox?: number[] | null;
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

const SNIPPET_LEADING_PUNCT = /^[,.;:!?。，；：！？…、（【「『《"''']/;
const SNIPPET_TRAILING_PUNCT = /[,.;:!?。，；：！？…、）】」』》"''']$/;

export function formatCitationSnippetExcerpt(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return trimmed;

  let excerpt = trimmed;
  if (!SNIPPET_LEADING_PUNCT.test(excerpt)) {
    excerpt = `...${excerpt}`;
  }
  if (!SNIPPET_TRAILING_PUNCT.test(excerpt)) {
    excerpt = `${excerpt}...`;
  }
  return excerpt;
}

const CITATION_PLACEHOLDER_PREFIX = "\uE000";
const CITATION_PLACEHOLDER_SUFFIX = "\uE001";
const CITATION_PLACEHOLDER_PATTERN = new RegExp(
  `${CITATION_PLACEHOLDER_PREFIX}(\\d+)${CITATION_PLACEHOLDER_SUFFIX}`,
  "g",
);

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function injectCitationPlaceholders(
  content: string,
  citations: Citation[],
  options?: { hideUnmatched?: boolean },
): string {
  if (!citations.length) return content;

  const pattern = /\[\s*(\d+)\s*\]|【\s*(\d+)\s*】/g;
  return content.replace(pattern, (match, n1, n2) => {
    const index = Number(n1 ?? n2) - 1;
    if (index < 0 || index >= citations.length) {
      return options?.hideUnmatched ? "" : match;
    }
    return `${CITATION_PLACEHOLDER_PREFIX}${index}${CITATION_PLACEHOLDER_SUFFIX}`;
  });
}

export function replaceCitationPlaceholdersWithButtons(
  html: string,
  citations: Citation[],
  options: {
    formatLabel: (index: number) => string;
    formatTitle: (citation: Citation) => string;
  },
): string {
  return html.replace(CITATION_PLACEHOLDER_PATTERN, (_, indexStr) => {
    const index = Number(indexStr);
    const citation = citations[index];
    if (!citation) return "";

    const label = escapeHtml(options.formatLabel(index));
    const title = escapeHtml(options.formatTitle(citation));
    return `<button type="button" class="citation-link" data-citation-index="${index}" title="${title}">${label}</button>`;
  });
}

export function splitContentIntoSections(content: string): string[] {
  const trimmed = content.trim();
  if (!trimmed) return [];

  if (/^#{1,6}\s/m.test(trimmed)) {
    return trimmed.split(/(?=^#{1,6}\s)/m).filter((part) => part.trim());
  }

  if (/\{\{embed:\s*\d+\s*\}\}/.test(trimmed)) {
    return [trimmed];
  }

  const paragraphs = trimmed.split(/\n{2,}/).filter((part) => part.trim());
  return paragraphs.length > 0 ? paragraphs : [trimmed];
}

export function citationToViewerTarget(citation: Citation): ViewerTarget {
  return {
    documentId: citation.document_id,
    documentName: citation.document_name,
    page: citation.page,
    section: citation.section,
    snippet: citation.snippet,
    bbox: citation.bbox ?? null,
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

function normalizedBboxKey(bbox?: number[] | null): string | null {
  if (!bbox || bbox.length !== 4) return null;
  return bbox.map((value) => Math.round(value * 10) / 10).join(",");
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

export function segmentsToRenderableContent(segments: MessageSegment[]): string {
  return segments
    .map((segment) => {
      if (segment.type === "text" || segment.type === "citation") {
        return segment.value;
      }
      return "";
    })
    .join("");
}

const COMPACT_MEDIA_TEXT_LIMIT = 140;
const COMPACT_SINGLE_LINE_LIMIT = 320;

export function isCompactMediaText(segments: MessageSegment[]): boolean {
  const text = stripInlineCitationMarkers(
    segmentsToRenderableContent(segments),
  ).trim();
  if (!text) return true;
  if (text.length < COMPACT_MEDIA_TEXT_LIMIT) return true;
  const lineCount = text.split("\n").filter((line) => line.trim()).length;
  if (lineCount <= 1 && text.length < COMPACT_SINGLE_LINE_LIMIT) return true;
  return false;
}

function splitTextAtFirstParagraph(text: string): [string, string] {
  const match = text.match(/\n{2,}/);
  if (!match || match.index === undefined) {
    return [text, ""];
  }
  const splitAt = match.index + match[0].length;
  return [text.slice(0, match.index), text.slice(splitAt)];
}

function takeFirstParagraphSegments(
  segments: MessageSegment[],
): { paired: MessageSegment[]; rest: MessageSegment[] } {
  const paired: MessageSegment[] = [];
  const rest: MessageSegment[] = [];

  for (let index = 0; index < segments.length; index += 1) {
    const segment = segments[index];
    if (segment.type !== "text") {
      if (paired.length === 0 || !rest.length) {
        paired.push(segment);
      } else {
        rest.push(segment);
      }
      continue;
    }

    const [first, remainder] = splitTextAtFirstParagraph(segment.value);
    if (first) {
      paired.push({ type: "text", value: first });
    }
    if (remainder) {
      rest.push({ type: "text", value: remainder });
      rest.push(...segments.slice(index + 1));
      break;
    }
  }

  return { paired, rest };
}

export type LayoutBlock =
  | { kind: "prose"; segments: MessageSegment[] }
  | { kind: "media"; embeds: MessageEmbed[]; segments: MessageSegment[]; compact?: boolean };

export function groupSegmentsForLayout(
  segments: MessageSegment[],
  seenEmbedKeys: Set<string> = new Set(),
): LayoutBlock[] {
  const blocks: LayoutBlock[] = [];
  let proseBuffer: MessageSegment[] = [];

  const flushProse = () => {
    if (proseBuffer.length === 0) return;
    blocks.push({ kind: "prose", segments: proseBuffer });
    proseBuffer = [];
  };

  const collectUniqueEmbeds = (embed: MessageEmbed): MessageEmbed[] => {
    const key = embedDedupeKey(embed);
    if (seenEmbedKeys.has(key)) {
      return [];
    }
    seenEmbedKeys.add(key);
    return [embed];
  };

  let index = 0;
  while (index < segments.length) {
    const segment = segments[index];
    if (segment.type !== "embed") {
      proseBuffer.push(segment);
      index += 1;
      continue;
    }

    flushProse();

    let mediaEmbeds = collectUniqueEmbeds(segment.embed);
    index += 1;

    while (index < segments.length && segments[index].type === "embed") {
      const next = segments[index];
      if (next.type === "embed") {
        mediaEmbeds.push(...collectUniqueEmbeds(next.embed));
      }
      index += 1;
    }

    const tailSegments: MessageSegment[] = [];
    while (index < segments.length && segments[index].type !== "embed") {
      tailSegments.push(segments[index]);
      index += 1;
    }

    const { paired, rest } = takeFirstParagraphSegments(tailSegments);
    if (rest.length > 0) {
      proseBuffer.push(...rest);
    }

    if (mediaEmbeds.length === 0) {
      if (paired.length > 0) {
        proseBuffer.push(...paired);
      }
      continue;
    }

    blocks.push({
      kind: "media",
      embeds: mediaEmbeds,
      segments: paired,
      compact: isCompactMediaText(paired),
    });
  }

  flushProse();
  return blocks;
}
