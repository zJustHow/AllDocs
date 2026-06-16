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
