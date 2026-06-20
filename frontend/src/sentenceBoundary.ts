const SENTENCE_END_CHARS = new Set(["。", "！", "？", ".", "!", "?", ";", ":", "；"]);

function isNumberedListMarkerAt(text: string, dotIndex: number): boolean {
  return (
    dotIndex > 0 &&
    text[dotIndex] === "." &&
    text[dotIndex - 1] >= "0" &&
    text[dotIndex - 1] <= "9"
  );
}

function isSentenceEndAt(text: string, index: number): boolean {
  const char = text[index];
  if (!SENTENCE_END_CHARS.has(char)) {
    return false;
  }
  return !(char === "." && isNumberedListMarkerAt(text, index));
}

function sentenceBoundaryEnd(text: string, fromIndex: number): number | null {
  for (let i = fromIndex; i < text.length; i += 1) {
    if (!isSentenceEndAt(text, i)) {
      continue;
    }
    let end = i + 1;
    while (end < text.length && (text[end] === " " || text[end] === "\t")) {
      end += 1;
    }
    return end;
  }
  return null;
}

/** Walk text runs separated by sentence boundaries. */
export function forEachTextRunBoundary(
  text: string,
  onRun: (run: string) => void,
  onBoundary: () => void,
): void {
  let pos = 0;
  while (pos < text.length) {
    const end = sentenceBoundaryEnd(text, pos);
    if (end === null) {
      onRun(text.slice(pos));
      return;
    }
    onRun(text.slice(pos, end));
    onBoundary();
    pos = end;
  }
}
