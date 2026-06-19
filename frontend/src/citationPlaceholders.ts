const CITATION_PLACEHOLDER_PREFIX = "\uE000";
const CITATION_PLACEHOLDER_SUFFIX = "\uE001";
export const CITATION_PLACEHOLDER_RE = new RegExp(
  `${CITATION_PLACEHOLDER_PREFIX}(\\d+)${CITATION_PLACEHOLDER_SUFFIX}`,
  "g",
);

export function citationPlaceholder(index: number): string {
  return `${CITATION_PLACEHOLDER_PREFIX}${index}${CITATION_PLACEHOLDER_SUFFIX}`;
}

export function hasCitationPlaceholders(content: string): boolean {
  CITATION_PLACEHOLDER_RE.lastIndex = 0;
  return CITATION_PLACEHOLDER_RE.test(content);
}
