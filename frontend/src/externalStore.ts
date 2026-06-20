import { useSyncExternalStore } from "react";

export interface ExternalStoreNotifier {
  notify: () => void;
  subscribe: (callback: () => void) => () => void;
}

export function createExternalStoreNotifier(): ExternalStoreNotifier {
  const listeners = new Set<() => void>();

  return {
    notify() {
      for (const listener of listeners) {
        listener();
      }
    },
    subscribe(callback) {
      listeners.add(callback);
      return () => listeners.delete(callback);
    },
  };
}

export interface MapStore<T> {
  get: (id: string, fallback: T) => T;
  init: (id: string, value: T) => void;
  set: (id: string, value: T) => void;
  delete: (id: string) => boolean;
  has: (id: string) => boolean;
}

export function createMapStore<T>(
  notifier: ExternalStoreNotifier,
): MapStore<T> {
  const values = new Map<string, T>();

  return {
    get(id, fallback) {
      return values.get(id) ?? fallback;
    },
    init(id, value) {
      values.set(id, value);
      notifier.notify();
    },
    set(id, value) {
      values.set(id, value);
      notifier.notify();
    },
    delete(id) {
      const deleted = values.delete(id);
      if (deleted) {
        notifier.notify();
      }
      return deleted;
    },
    has(id) {
      return values.has(id);
    },
  };
}

export function createExternalStoreHook<T>(
  subscribe: ExternalStoreNotifier["subscribe"],
  getSnapshot: (id: string) => T,
  serverFallback: T,
) {
  return (id: string) =>
    useSyncExternalStore(
      subscribe,
      () => getSnapshot(id),
      () => serverFallback,
    );
}
