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

  if (typeof window.matchMedia !== "function") {
    window.matchMedia = (query: string): MediaQueryList => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    });
  }
}
