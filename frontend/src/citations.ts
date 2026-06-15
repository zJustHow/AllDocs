import type { Citation } from "./types";

export interface ViewerTarget {
  documentId: string;
  documentName: string;
  page: number | null;
  section: string | null;
  snippet?: string;
  pageCount?: number | null;
}

export function getCitationIndex(citation: Citation, citations: Citation[]): number {
  return citations.findIndex(
    (item) =>
      item.document_id === citation.document_id &&
      item.page === citation.page &&
      item.section === citation.section,
  );
}

export function formatCitationLabel(index: number): string {
  return `[${index + 1}]`;
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

function parseInlineCitationRef(inner: string, citations: Citation[]): Citation | null {
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
      citation.document_name.includes(docName) || docName.includes(citation.document_name),
  );
  if (byName) return byName;

  if (page !== null) {
    return citations.find((citation) => citation.page === page) ?? null;
  }

  return null;
}

export type MessageSegment =
  | { type: "text"; value: string }
  | { type: "citation"; value: string; citation: Citation };

export function splitMessageWithCitations(
  content: string,
  citations: Citation[],
): MessageSegment[] {
  if (!citations.length) {
    return [{ type: "text", value: content }];
  }

  const pattern = /\[\s*(\d+)\s*\]|【\s*(\d+)\s*】|\[([^\]]+)\]/g;
  const segments: MessageSegment[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(content)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: "text", value: content.slice(lastIndex, match.index) });
    }

    const numericRef = match[1] ?? match[2];
    if (numericRef) {
      const index = Number(numericRef) - 1;
      const citation = citations[index];
      if (citation) {
        segments.push({ type: "citation", value: match[0], citation });
      } else {
        segments.push({ type: "text", value: match[0] });
      }
    } else {
      const inner = match[3];
      const citation = parseInlineCitationRef(inner, citations);
      if (citation) {
        segments.push({ type: "citation", value: match[0], citation });
      } else {
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
