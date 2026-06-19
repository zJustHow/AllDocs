import type { Citation, MessageEmbed } from "./types";
import { citationPlaceholder } from "./citationPlaceholders";
import {
  embedDedupeKey,
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

export function formatCitationLabel(index: number): string {
  return `[${index + 1}]`;
}

const SNIPPET_LEADING_PUNCT = /^[,.;:!?。，；：！？…、（【「『《"''']/;
const SNIPPET_TRAILING_PUNCT = /[,.;:!?。，；：！？…、）】」』》"''']$/;
const TRAILING_PUNCT_ONLY = /^[\s,.;:!?。，；：！？…、）】」』《"''']+$/;
/** Flush embeds once the preceding sentence ends (Chinese + English punctuation). */
// Keep newlines so Markdown list items (e.g. after "[1]。\n- item") stay on separate lines.
const INLINE_RUN_BOUNDARY = /(?<=[。！？.!?；;:])[ \t]*/;

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
  | { type: "citation"; value: string; citation: Citation; index: number }
  | { type: "embed"; value: string; embed: MessageEmbed };

function indexEmbedsBySentence(
  embeds: MessageEmbed[],
): Map<number, MessageEmbed[]> {
  const bySentence = new Map<number, MessageEmbed[]>();
  for (const embed of embeds) {
    if (embed.sentence_index == null) continue;
    const bucket = bySentence.get(embed.sentence_index) ?? [];
    bucket.push(embed);
    bySentence.set(embed.sentence_index, bucket);
  }
  return bySentence;
}

function indexEmbedsByRef(embeds: MessageEmbed[]): Map<number, MessageEmbed[]> {
  const byRef = new Map<number, MessageEmbed[]>();
  for (const embed of embeds) {
    if (embed.ref == null) continue;
    const bucket = byRef.get(embed.ref) ?? [];
    bucket.push(embed);
    byRef.set(embed.ref, bucket);
  }
  return byRef;
}

function appendEmbedsForSentence(
  segments: MessageSegment[],
  sentenceIndex: number,
  embedsBySentence: Map<number, MessageEmbed[]>,
  shownEmbedKeys: Set<string>,
): void {
  for (const embed of embedsBySentence.get(sentenceIndex) ?? []) {
    const key = embedDedupeKey(embed);
    if (shownEmbedKeys.has(key)) continue;
    shownEmbedKeys.add(key);
    segments.push({ type: "embed", value: "", embed });
  }
}

function appendEmbedsForRef(
  segments: MessageSegment[],
  ref: number,
  embedsByRef: Map<number, MessageEmbed[]>,
  shownEmbedKeys: Set<string>,
): void {
  for (const embed of embedsByRef.get(ref) ?? []) {
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
  },
): MessageSegment[] {
  const hideUnmatched = options?.hideUnmatched ?? false;
  const embeds = options?.embeds ?? [];
  const embedsBySentence = indexEmbedsBySentence(embeds);
  const embedsByRef = indexEmbedsByRef(embeds);
  const pattern = new RegExp(messageTokenPattern.source, "g");
  const shownEmbedKeys = new Set<string>();

  if (!citations.length && !embeds.length) {
    return [{ type: "text", value: stripInlineMarkers(content) }];
  }

  const segments: MessageSegment[] = [];
  let currentSentenceIndex = 0;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  const flushEmbedsForCurrentSentence = () => {
    appendEmbedsForSentence(
      segments,
      currentSentenceIndex,
      embedsBySentence,
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
      appendEmbedsForRef(
        segments,
        Number(embedRef),
        embedsByRef,
        shownEmbedKeys,
      );
      lastIndex = match.index + match[0].length;
      continue;
    }

    const numericRef = match[2] ?? match[3];
    if (numericRef) {
      const index = Number(numericRef) - 1;
      const citation = citations[index];
      if (citation) {
        segments.push({ type: "citation", value: match[0], citation, index });
      } else if (!hideUnmatched) {
        segments.push({ type: "text", value: match[0] });
      }
    } else {
      const inner = match[4];
      const citation = parseInlineCitationRef(inner, citations);
      if (citation) {
        const index = citations.indexOf(citation);
        segments.push({ type: "citation", value: match[0], citation, index });
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
  return ORPHAN_INLINE_SUFFIX.test(segmentsDisplayText(segments).trim());
}

export function segmentsDisplayText(segments: MessageSegment[]): string {
  return segments
    .map((segment) => {
      if (segment.type === "text" || segment.type === "citation") {
        return segment.value;
      }
      return "";
    })
    .join("");
}

/** Build a single Markdown input from split segments; citations become inline placeholders. */
export function segmentsToMarkdownSource(segments: MessageSegment[]): string {
  return segments
    .map((segment) => {
      if (segment.type === "text") return segment.value;
      if (segment.type === "citation") {
        return segment.index >= 0 ? citationPlaceholder(segment.index) : "";
      }
      return "";
    })
    .join("");
}

export function proseSegmentsHaveContent(segments: MessageSegment[]): boolean {
  return segments.some((segment) => {
    if (segment.type === "text") return segment.value.trim().length > 0;
    if (segment.type === "citation") return segment.index >= 0;
    return false;
  });
}
