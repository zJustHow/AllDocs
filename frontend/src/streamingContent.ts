import { useSyncExternalStore } from "react";

const contentById = new Map<string, string>();
const listeners = new Set<() => void>();

function notify() {
  for (const listener of listeners) {
    listener();
  }
}

export function initStreamingContent(messageId: string): void {
  contentById.set(messageId, "");
  notify();
}

export function appendStreamingContent(messageId: string, delta: string): void {
  contentById.set(messageId, (contentById.get(messageId) ?? "") + delta);
  notify();
}

export function getStreamingContent(messageId: string): string {
  return contentById.get(messageId) ?? "";
}

export function clearStreamingContent(messageId: string): void {
  if (!contentById.delete(messageId)) return;
  notify();
}

function subscribe(callback: () => void): () => void {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

/** Subscribe only the active streaming message — avoids App-wide re-renders on each delta. */
export function useStreamingContent(messageId: string): string {
  return useSyncExternalStore(
    subscribe,
    () => getStreamingContent(messageId),
    () => "",
  );
}
