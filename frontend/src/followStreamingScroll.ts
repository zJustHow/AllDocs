import { readComposerStackHeight } from "./hooks/useComposerStackHeight";

/** Scroll the chat container just enough to keep the streaming cursor visible. */
export function followCursorInContainer(
  cursor: HTMLElement,
  container: HTMLElement,
  padding = readComposerStackHeight(container),
): void {
  const cursorRect = cursor.getBoundingClientRect();
  const containerRect = container.getBoundingClientRect();
  const overflow = cursorRect.bottom - (containerRect.bottom - padding);
  if (overflow > 0) {
    container.scrollTop += overflow;
  }
}
