const MAX_ENTRIES = 128;

const htmlByKey = new Map<string, string>();

export type MarkdownCacheKind = "block" | "citations";

function cacheKey(content: string, kind: MarkdownCacheKind): string {
  return `${kind === "citations" ? "c" : "b"}\0${content}`;
}

function touchEntry(key: string, html: string): string {
  htmlByKey.delete(key);
  htmlByKey.set(key, html);
  while (htmlByKey.size > MAX_ENTRIES) {
    const oldest = htmlByKey.keys().next().value;
    if (oldest) htmlByKey.delete(oldest);
  }
  return html;
}

export function getCachedMarkdownHtml(
  content: string,
  kind: MarkdownCacheKind,
): string | null {
  const key = cacheKey(content, kind);
  const hit = htmlByKey.get(key);
  if (!hit) return null;
  htmlByKey.delete(key);
  htmlByKey.set(key, hit);
  return hit;
}

export function setCachedMarkdownHtml(
  content: string,
  kind: MarkdownCacheKind,
  html: string,
): string {
  return touchEntry(cacheKey(content, kind), html);
}
