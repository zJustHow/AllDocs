const MAX_ENTRIES = 128;

const htmlByKey = new Map<string, string>();

function cacheKey(content: string, inline: boolean): string {
  return `${inline ? "i" : "b"}\0${content}`;
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
  inline: boolean,
): string | null {
  const key = cacheKey(content, inline);
  const hit = htmlByKey.get(key);
  if (!hit) return null;
  htmlByKey.delete(key);
  htmlByKey.set(key, hit);
  return hit;
}

export function setCachedMarkdownHtml(
  content: string,
  inline: boolean,
  html: string,
): string {
  return touchEntry(cacheKey(content, inline), html);
}
