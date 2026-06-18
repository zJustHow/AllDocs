import type { Citation, MessageEmbed } from "./types";
import {
  embedDedupeKey,
  formatEmbedMarker,
  inlineCitationMarkerSource,
  inlineCitationRefPattern,
  messageTokenPattern,
  stripInlineMarkers,
} from "./shared/contract";

export { embedDedupeKey } from "./shared/contract";

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

export function stripInlineCitationMarkers(content: string): string {
  return stripInlineMarkers(content);
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

export function normalizeCitationLayout(content: string): string {
  let result = content;
  const citation = inlineCitationMarkerSource;
  result = result.replace(
    new RegExp(`\\n{2,}(?=\\s*(?:${citation}))`, "g"),
    "",
  );
  result = result.replace(new RegExp(`\\n(?=[ \\t]*(?:${citation}))`, "g"), "");
  result = result.replace(
    new RegExp(`((?:${citation})+)\\s*\\n+\\s*([;；。，：！？、])`, "g"),
    "$1$2",
  );
  result = result.replace(
    new RegExp(
      `((?:${citation})+)\\s+([;；。，：！？、])(?=\\s*(?:\\n|$))`,
      "g",
    ),
    "$1$2",
  );
  return result;
}

const CITATION_ONLY_SECTION = new RegExp(
  `^(?:\\s*(?:${inlineCitationMarkerSource})\\s*)+[;；。，：！？、]?$`,
);

function mergeCitationOnlySections(sections: string[]): string[] {
  const merged: string[] = [];
  for (const section of sections) {
    const trimmed = section.trim();
    if (merged.length > 0 && CITATION_ONLY_SECTION.test(trimmed)) {
      merged[merged.length - 1] = `${merged[merged.length - 1]}${trimmed}`;
      continue;
    }
    merged.push(section);
  }
  return merged;
}

const HORIZONTAL_RULE_ONLY = /^[-*_]{3,}\s*$/;

function getLeadingHeadingLevel(text: string): number | null {
  const match = text.match(/^#{1,6}(?=\s)/);
  return match ? match[0].length : null;
}

function mergeSubheadingSections(sections: string[]): string[] {
  if (sections.length <= 1) return sections;

  const merged: string[] = [];
  let sectionRootLevel: number | null = null;

  for (const section of sections) {
    const level = getLeadingHeadingLevel(section);

    if (
      merged.length > 0 &&
      level !== null &&
      sectionRootLevel !== null &&
      level > sectionRootLevel
    ) {
      const previous = merged[merged.length - 1];
      merged[merged.length - 1] =
        `${previous.trimEnd()}\n\n${section.trimStart()}`;
      continue;
    }

    merged.push(section);
    sectionRootLevel = level;
  }

  return merged;
}

function normalizeSectionText(text: string): string {
  const trimmed = text.trim();
  if (!trimmed || HORIZONTAL_RULE_ONLY.test(trimmed)) {
    return "";
  }
  return trimmed;
}

function normalizeSections(sections: string[]): string[] {
  return sections
    .map((section) => normalizeSectionText(section))
    .filter((section) => section.length > 0);
}

const ORPHAN_CITATION_BLOCK_HTML =
  /<(?:p|span class="md-inline")>\s*((?:<button type="button" class="citation-link"[^>]*>[^<]*<\/button>\s*)+[;；。，：！？、]?)\s*<\/(?:p|span)>/i;

function mergeOneOrphanCitationBlock(html: string): string {
  const match = html.match(ORPHAN_CITATION_BLOCK_HTML);
  if (!match) return html;

  const citationHtml = match[1];
  const withoutBlock = html.replace(ORPHAN_CITATION_BLOCK_HTML, "");

  const lastListItemClose = withoutBlock.lastIndexOf("</li>");
  if (lastListItemClose !== -1) {
    return (
      withoutBlock.slice(0, lastListItemClose) +
      citationHtml +
      withoutBlock.slice(lastListItemClose)
    );
  }

  const lastInlineClose = withoutBlock.lastIndexOf("</span>");
  const lastParagraphClose = withoutBlock.lastIndexOf("</p>");
  const lastTextClose = Math.max(lastInlineClose, lastParagraphClose);
  if (lastTextClose !== -1) {
    return (
      withoutBlock.slice(0, lastTextClose) +
      citationHtml +
      withoutBlock.slice(lastTextClose)
    );
  }

  return html;
}

export function mergeOrphanCitationParagraphs(html: string): string {
  let result = html;
  let previous = "";
  while (result !== previous) {
    previous = result;
    result = mergeOneOrphanCitationBlock(result);
  }
  return result;
}

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

  const normalized = normalizeCitationLayout(content);
  return normalized.replace(inlineCitationRefPattern, (match, n1, n2) => {
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

function sectionContainsCitationRef(sectionText: string, ref: number): boolean {
  return new RegExp(`(?:\\[\\s*${ref}\\s*\\]|【\\s*${ref}\\s*】)`).test(
    sectionText,
  );
}

function findSectionIndexForEmbedRef(
  sectionTexts: string[],
  ref: number,
): number {
  let lastMatch = -1;
  for (let i = 0; i < sectionTexts.length; i += 1) {
    if (sectionContainsCitationRef(sectionTexts[i], ref)) {
      lastMatch = i;
    }
  }
  return lastMatch;
}

function stripEmbedMarkerFromText(text: string, ref: number): string {
  const marker = formatEmbedMarker(ref);
  return text
    .replace(marker, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function removeEmbedMarkerFromSegments(
  segments: MessageSegment[],
  ref: number,
): MessageSegment[] {
  return segments
    .map((segment) => {
      if (segment.type !== "text") return segment;
      return {
        ...segment,
        value: stripEmbedMarkerFromText(segment.value, ref),
      };
    })
    .filter((segment) => segment.type !== "text" || segment.value.length > 0);
}

export function reassignEmbedsAcrossSections(
  sectionTexts: string[],
  segmentsBySection: MessageSegment[][],
): MessageSegment[][] {
  const result = segmentsBySection.map((segments) => [...segments]);

  for (let fromIdx = 0; fromIdx < result.length; fromIdx += 1) {
    for (let i = result[fromIdx].length - 1; i >= 0; i -= 1) {
      const segment = result[fromIdx][i];
      if (segment.type !== "embed") continue;

      const ref = segment.embed.ref;
      if (sectionContainsCitationRef(sectionTexts[fromIdx], ref)) continue;

      const toIdx = findSectionIndexForEmbedRef(sectionTexts, ref);
      if (toIdx < 0 || toIdx === fromIdx) continue;

      result[fromIdx].splice(i, 1);
      result[fromIdx] = removeEmbedMarkerFromSegments(
        result[fromIdx],
        ref,
      );
      result[toIdx] = [segment, ...result[toIdx]];
    }
  }

  return result;
}

export function splitContentIntoSections(content: string): string[] {
  const trimmed = normalizeCitationLayout(content.trim());
  if (!trimmed) return [];

  if (/^#{1,6}\s/m.test(trimmed)) {
    return normalizeSections(
      mergeCitationOnlySections(
        mergeSubheadingSections(
          trimmed.split(/(?=^#{1,6}\s)/m).filter((part) => part.trim()),
        ),
      ),
    );
  }

  return normalizeSections([trimmed]);
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

function findEmbedsForRef(ref: number, embeds: MessageEmbed[]): MessageEmbed[] {
  return embeds.filter((item) => item.ref === ref);
}

function appendEmbedsForRef(
  segments: MessageSegment[],
  ref: number,
  embeds: MessageEmbed[],
  shownEmbedKeys: Set<string>,
): void {
  for (const embed of findEmbedsForRef(ref, embeds)) {
    const key = embedDedupeKey(embed);
    if (shownEmbedKeys.has(key)) continue;
    shownEmbedKeys.add(key);
    segments.push({ type: "embed", value: "", embed });
  }
}

export function splitMessageWithCitations(
  content: string,
  citations: Citation[],
  options?: { hideUnmatched?: boolean; embeds?: MessageEmbed[] },
): MessageSegment[] {
  const hideUnmatched = options?.hideUnmatched ?? false;
  const embeds = options?.embeds ?? [];
  const pattern = new RegExp(messageTokenPattern.source, "g");
  const shownEmbedKeys = new Set<string>();

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
      appendEmbedsForRef(segments, Number(embedRef), embeds, shownEmbedKeys);
      lastIndex = match.index + match[0].length;
      continue;
    }

    const numericRef = match[2] ?? match[3];
    if (numericRef) {
      const index = Number(numericRef) - 1;
      const citation = citations[index];
      if (citation) {
        segments.push({ type: "citation", value: match[0], citation });
        appendEmbedsForRef(
          segments,
          Number(numericRef),
          embeds,
          shownEmbedKeys,
        );
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

export function segmentsToRenderableContent(
  segments: MessageSegment[],
): string {
  return normalizeCitationLayout(
    segments
      .map((segment) => {
        if (segment.type === "text" || segment.type === "citation") {
          return segment.value;
        }
        return "";
      })
      .join(""),
  );
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
