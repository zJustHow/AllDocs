import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
});

if (typeof window !== "undefined") {
  HTMLElement.prototype.scrollTo =
    HTMLElement.prototype.scrollTo ??
    vi.fn<HTMLElement["scrollTo"]>();

  HTMLElement.prototype.scrollIntoView =
    HTMLElement.prototype.scrollIntoView ??
    vi.fn<HTMLElement["scrollIntoView"]>();

  class ResizeObserverMock {
    observe = vi.fn();
    disconnect = vi.fn();
    unobserve = vi.fn();
  }

  class IntersectionObserverMock {
    observe = vi.fn();
    disconnect = vi.fn();
    unobserve = vi.fn();
  }

  globalThis.ResizeObserver =
    globalThis.ResizeObserver ?? (ResizeObserverMock as typeof ResizeObserver);
  globalThis.IntersectionObserver =
    globalThis.IntersectionObserver ??
    (IntersectionObserverMock as typeof IntersectionObserver);
}
