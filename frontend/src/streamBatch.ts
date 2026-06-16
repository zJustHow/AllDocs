/** Batches rapid stream events into fewer state updates (~50ms). */
export function createEventBatcher<T>(append: (items: T[]) => void, delayMs = 50) {
  let pending: T[] = [];
  let timer: ReturnType<typeof setTimeout> | null = null;

  const flush = () => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    if (pending.length) {
      const batch = pending;
      pending = [];
      append(batch);
    }
  };

  return {
    push(item: T) {
      pending.push(item);
      if (!timer) {
        timer = setTimeout(flush, delayMs);
      }
    },
    flush,
  };
}

/** Batches rapid stream deltas into fewer state updates (~50ms). */
export function createDeltaBatcher(append: (delta: string) => void) {
  let pending = "";
  let timer: ReturnType<typeof setTimeout> | null = null;

  const flush = () => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    if (pending) {
      const chunk = pending;
      pending = "";
      append(chunk);
    }
  };

  return {
    push(delta: string) {
      pending += delta;
      if (!timer) {
        timer = setTimeout(flush, 50);
      }
    },
    flush,
  };
}
