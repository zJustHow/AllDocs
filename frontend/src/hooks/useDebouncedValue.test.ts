/** @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDebouncedValue } from "./useDebouncedValue";

describe("useDebouncedValue", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("debounces non-empty values", () => {
    const { result, rerender } = renderHook(
      ({ value, delayMs }) => useDebouncedValue(value, delayMs),
      { initialProps: { value: "a", delayMs: 200 } },
    );

    expect(result.current).toBe("a");

    rerender({ value: "ab", delayMs: 200 });
    expect(result.current).toBe("a");

    act(() => {
      vi.advanceTimersByTime(199);
    });
    expect(result.current).toBe("a");

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe("ab");
  });

  it("clears immediately for empty, null, and undefined values", () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue<string | null | undefined>(value, 200),
      { initialProps: { value: "query" as string | null | undefined } },
    );

    rerender({ value: "" });
    expect(result.current).toBe("");

    rerender({ value: "query" });
    rerender({ value: null });
    expect(result.current).toBeNull();

    rerender({ value: "query" });
    rerender({ value: undefined });
    expect(result.current).toBeUndefined();
  });
});
