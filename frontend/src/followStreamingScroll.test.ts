import { describe, expect, it, vi } from "vitest";
import { followCursorInContainer } from "./followStreamingScroll";

describe("followCursorInContainer", () => {
  it("scrolls down when the cursor extends below the visible area", () => {
    const container = {
      scrollTop: 0,
      getBoundingClientRect: () => ({ bottom: 500 }),
    } as HTMLElement;
    const cursor = {
      getBoundingClientRect: () => ({ bottom: 520 }),
    } as HTMLElement;

    followCursorInContainer(cursor, container, 24);

    expect(container.scrollTop).toBe(44);
  });

  it("does not scroll when the cursor is already visible", () => {
    const container = {
      scrollTop: 100,
      getBoundingClientRect: () => ({ bottom: 500 }),
    } as HTMLElement;
    const cursor = {
      getBoundingClientRect: () => ({ bottom: 460 }),
    } as HTMLElement;

    followCursorInContainer(cursor, container);

    expect(container.scrollTop).toBe(100);
  });
});
