import {
  createExternalStoreHook,
  createExternalStoreNotifier,
  createMapStore,
} from "./externalStore";

const notifier = createExternalStoreNotifier();
const contentStore = createMapStore<string>(notifier);

export function initStreamingContent(messageId: string): void {
  contentStore.init(messageId, "");
}

export function appendStreamingContent(messageId: string, delta: string): void {
  contentStore.set(messageId, contentStore.get(messageId, "") + delta);
}

export function getStreamingContent(messageId: string): string {
  return contentStore.get(messageId, "");
}

export function clearStreamingContent(messageId: string): void {
  contentStore.delete(messageId);
}

export const subscribeStreamingContent = notifier.subscribe;

/** Subscribe only the active streaming message — avoids App-wide re-renders on each delta. */
export const useStreamingContent = createExternalStoreHook(
  notifier.subscribe,
  getStreamingContent,
  "",
);
