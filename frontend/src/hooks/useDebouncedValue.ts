import { useEffect, useState } from "react";

/** Debounce updates; empty string / null-like clears apply immediately. */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const clearImmediately =
      value === "" ||
      value === null ||
      value === undefined;

    if (clearImmediately) {
      setDebounced(value);
      return;
    }

    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
