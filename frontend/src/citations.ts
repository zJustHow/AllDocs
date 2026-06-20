import type { Citation, MessageEmbed } from "./types";
import { citationPlaceholder } from "./citationPlaceholders";
import {
  embedDedupeKey,
  messageTokenPattern,
  stripInlineMarkers,
} from "./shared/contract";
import { forEachTextRunBoundary } from "./sentenceBoundary";
import type { BboxRegion } from "./viewerPosition";

export { embedDedupeKey };

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
const SNIPPET_TRAILING_PUNCT = /[,.;:!?。，；：！？…、）】」』《"''']$/;
const TRAILING_PUNCT_ONLY = /^[\s,.;:!?。，；：！？…、）】」』《"''']+$/;

export function formatCitationTooltip(
  citation: Citation,
  pageHint = "",
): string {
  return `${citation.document_name}${pageHint}${
    citation.section ? ` · ${citation.section}` : ""
  }\n${formatCitationSnippetExcerpt(citation.snippet)}`;
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
  const numericMatch = inner.match(/^\s*\[?(\d+)\]?\s*$/);
  if (numericMatch) {
    return citations[Number(numericMatch[1]) - 1] ?? null;
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
  | { type: "embed"; embed: MessageEmbed };

function indexEmbedsBy(
  embeds: MessageEmbed[],
  pickIndex: (embed: MessageEmbed) => number | null | undefined,
): Map<number, MessageEmbed[]> {
  const byKey = new Map<number, MessageEmbed[]>();
  for (const embed of embeds) {
    const index = pickIndex(embed);
    if (index == null) continue;
    const bucket = byKey.get(index) ?? [];
    bucket.push(embed);
    byKey.set(index, bucket);
  }
  return byKey;
}

function appendEmbedsForKey(
  segments: MessageSegment[],
  key: number,
  embedsByKey: Map<number, MessageEmbed[]>,
  shownEmbedKeys: Set<string>,
): void {
  for (const embed of embedsByKey.get(key) ?? []) {
    const dedupeKey = embedDedupeKey(embed);
    if (shownEmbedKeys.has(dedupeKey)) continue;
    shownEmbedKeys.add(dedupeKey);
    segments.push({ type: "embed", embed });
  }
}

function pushCitationSegment(
  segments: MessageSegment[],
  token: string,
  citation: Citation | null | undefined,
  index: number,
  hideUnmatched: boolean,
): void {
  if (citation) {
    segments.push({ type: "citation", value: token, citation, index });
    return;
  }
  if (!hideUnmatched) {
    segments.push({ type: "text", value: token });
  }
}

export function splitMessageWithCitations(
  content: string,
  citations: Citation[],
  options?: {
    hideUnmatched?: boolean;
    embeds?: MessageEmbed[];
    /** Skip sentence-boundary embed placement during streaming. */
    streaming?: boolean;
  },
): MessageSegment[] {
  const hideUnmatched = options?.hideUnmatched ?? false;
  const streaming = options?.streaming ?? false;
  const embeds = options?.embeds ?? [];
  const embedsBySentence = streaming
    ? new Map<number, MessageEmbed[]>()
    : indexEmbedsBy(embeds, (embed) => embed.sentence_index);
  const embedsByRef = indexEmbedsBy(embeds, (embed) => embed.ref);
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
    if (streaming) return;
    appendEmbedsForKey(
      segments,
      currentSentenceIndex,
      embedsBySentence,
      shownEmbedKeys,
    );
    currentSentenceIndex += 1;
  };

  const appendText = (text: string) => {
    if (!text) return;
    if (streaming) {
      segments.push({ type: "text", value: text });
      return;
    }
    forEachTextRunBoundary(
      text,
      (run) => {
        segments.push({ type: "text", value: run });
      },
      flushEmbedsForCurrentSentence,
    );
  };

  while ((match = pattern.exec(content)) !== null) {
    if (match.index > lastIndex) {
      appendText(content.slice(lastIndex, match.index));
    }

    const embedRef = match[1];
    if (embedRef) {
      flushEmbedsForCurrentSentence();
      appendEmbedsForKey(
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
      pushCitationSegment(
        segments,
        match[0],
        citations[index],
        index,
        hideUnmatched,
      );
    } else {
      const inner = match[4];
      const citation = parseInlineCitationRef(inner, citations);
      pushCitationSegment(
        segments,
        match[0],
        citation,
        citation ? citations.indexOf(citation) : -1,
        hideUnmatched,
      );
    }
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < content.length) {
    appendText(content.slice(lastIndex));
  }
  if (!streaming) {
    flushEmbedsForCurrentSentence();
  }

  if (!segments.length) {
    return [{ type: "text", value: content }];
  }
  if (streaming) {
    return segments;
  }
  return absorbTrailingPunctuationBeforeEmbeds(segments);
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
