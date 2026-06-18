import type { Citation, MessageEmbed } from "./types";
import {
  embedDedupeKey,
  inlineCitationRefPattern,
  messageTokenPattern,
  stripInlineMarkers,
} from "./shared/contract";
import type { BboxRegion } from "./viewerPosition";

export { embedDedupeKey } from "./shared/contract";

export interface ViewerTarget {
  documentId: string;
  documentName: string;
  contentType?: string | null;
  page: number | null;
  section: string | null;
  snippet?: string;
  pageCount?: number | null;
  regions: BboxRegion[];
}

export function stripInlineCitationMarkers(content: string): string {
  return stripInlineMarkers(content);
}

export function formatCitationLabel(index: number): string {
  return `[${index + 1}]`;
}

const SNIPPET_LEADING_PUNCT = /^[,.;:!?。，；：！？…、（【「『《"''']/;
const SNIPPET_TRAILING_PUNCT = /[,.;:!?。，；：！？…、）】」』》"''']$/;
const TRAILING_PUNCT_ONLY = /^[\s,.;:!?。，；：！？…、）】」』《"''']+$/;
/** Flush embeds once the preceding sentence ends (Chinese + English punctuation). */
const INLINE_RUN_BOUNDARY = /(?<=[。！？.!?；;:])\s*/;

function appendTextSegment(
  segments: MessageSegment[],
  text: string,
  flushEmbedsForCurrentSentence: () => void,
): void {
  if (!text) return;

  let rest = text;
  while (rest.length > 0) {
    const match = INLINE_RUN_BOUNDARY.exec(rest);
    if (!match || match.index === undefined) {
      segments.push({ type: "text", value: rest });
      return;
    }

    if (match.index > 0) {
      segments.push({ type: "text", value: rest.slice(0, match.index) });
    }

    flushEmbedsForCurrentSentence();
    rest = rest.slice(match.index + match[0].length);
  }
}

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

  return content.replace(inlineCitationRefPattern, (match, n1, n2) => {
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

export function citationToViewerTarget(citation: Citation): ViewerTarget {
  return {
    documentId: citation.document_id,
    documentName: citation.document_name,
    page: citation.page,
    section: citation.section,
    snippet: citation.snippet,
    regions: citation.regions.map((region) => ({
      page: region.page,
      bbox: region.bbox as BboxRegion["bbox"],
    })),
  };
}

export function embedToViewerTarget(embed: MessageEmbed): ViewerTarget {
  return {
    documentId: embed.document_id,
    documentName: embed.document_name ?? "",
    page: embed.page,
    section: embed.caption ?? null,
    regions: embed.regions.map((region) => ({
      page: region.page,
      bbox: region.bbox as BboxRegion["bbox"],
    })),
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

function findEmbedsForSentence(
  sentenceIndex: number,
  embeds: MessageEmbed[],
): MessageEmbed[] {
  return embeds.filter((item) => item.sentence_index === sentenceIndex);
}

function appendEmbedsForSentence(
  segments: MessageSegment[],
  sentenceIndex: number,
  embeds: MessageEmbed[],
  shownEmbedKeys: Set<string>,
): void {
  for (const embed of findEmbedsForSentence(sentenceIndex, embeds)) {
    const key = embedDedupeKey(embed);
    if (shownEmbedKeys.has(key)) continue;
    shownEmbedKeys.add(key);
    segments.push({ type: "embed", value: "", embed });
  }
}

function appendEmbedsForRef(
  segments: MessageSegment[],
  ref: number,
  embeds: MessageEmbed[],
  shownEmbedKeys: Set<string>,
): void {
  for (const embed of embeds.filter((item) => item.ref === ref)) {
    const key = embedDedupeKey(embed);
    if (shownEmbedKeys.has(key)) continue;
    shownEmbedKeys.add(key);
    segments.push({ type: "embed", value: "", embed });
  }
}

export function splitMessageWithCitations(
  content: string,
  citations: Citation[],
  options?: {
    hideUnmatched?: boolean;
    embeds?: MessageEmbed[];
    attachEmbedsToCitations?: boolean;
  },
): MessageSegment[] {
  const hideUnmatched = options?.hideUnmatched ?? false;
  const embeds = options?.embeds ?? [];
  const attachEmbedsToCitations = options?.attachEmbedsToCitations ?? true;
  const pattern = new RegExp(messageTokenPattern.source, "g");
  const shownEmbedKeys = new Set<string>();

  if (!citations.length && !embeds.length) {
    return [{ type: "text", value: stripInlineCitationMarkers(content) }];
  }

  const segments: MessageSegment[] = [];
  let currentSentenceIndex = 0;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  const flushEmbedsForCurrentSentence = () => {
    if (!attachEmbedsToCitations) return;
    appendEmbedsForSentence(
      segments,
      currentSentenceIndex,
      embeds,
      shownEmbedKeys,
    );
    currentSentenceIndex += 1;
  };

  while ((match = pattern.exec(content)) !== null) {
    if (match.index > lastIndex) {
      appendTextSegment(
        segments,
        content.slice(lastIndex, match.index),
        flushEmbedsForCurrentSentence,
      );
    }

    const embedRef = match[1];
    if (embedRef) {
      flushEmbedsForCurrentSentence();
      if (attachEmbedsToCitations) {
        appendEmbedsForRef(segments, Number(embedRef), embeds, shownEmbedKeys);
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
    appendTextSegment(
      segments,
      content.slice(lastIndex),
      flushEmbedsForCurrentSentence,
    );
  }
  flushEmbedsForCurrentSentence();

  return segments.length
    ? absorbTrailingPunctuationBeforeEmbeds(segments)
    : [{ type: "text", value: content }];
}

function absorbTrailingPunctuationBeforeEmbeds(
  segments: MessageSegment[],
): MessageSegment[] {
  const result = [...segments];

  while (result.length >= 2) {
    let tail = result.length - 1;
    while (tail >= 0 && result[tail].type === "embed") {
      tail -= 1;
    }
    if (tail < 0) {
      break;
    }

    const punct = result[tail];
    if (punct.type !== "text" || !TRAILING_PUNCT_ONLY.test(punct.value)) {
      break;
    }

    tail -= 1;
    if (tail < 0) {
      break;
    }

    const target = result[tail];
    if (target.type !== "text" && target.type !== "citation") {
      break;
    }

    result[tail] = { ...target, value: target.value + punct.value };
    result.splice(tail + 1, 1);
  }

  return result;
}

export function isTrailingPunctuationOnly(text: string): boolean {
  return TRAILING_PUNCT_ONLY.test(text);
}

const ORPHAN_INLINE_SUFFIX =
  /^[\s,.;:!?。，；：！？…、）】」』《"'''\[\]【】0-9]+$/;

export function isOrphanInlineSuffix(segments: MessageSegment[]): boolean {
  if (!segments.length) return false;
  return ORPHAN_INLINE_SUFFIX.test(
    segmentsToRenderableContent(segments).trim(),
  );
}

export function segmentsToRenderableContent(
  segments: MessageSegment[],
): string {
  return segments
    .map((segment) => {
      if (segment.type === "text" || segment.type === "citation") {
        return segment.value;
      }
      return "";
    })
    .join("");
}
