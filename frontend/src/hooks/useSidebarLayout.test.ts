/** @vitest-environment jsdom */
import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as layout from "../layout";
import { renderHookWithI18n } from "./testUtils";
import { useSidebarLayout } from "./useSidebarLayout";

describe("useSidebarLayout", () => {
  let mediaListeners: Map<string, (event: MediaQueryListEvent) => void>;

  beforeEach(() => {
    mediaListeners = new Map();
    vi.spyOn(layout, "isMobileViewport").mockReturnValue(false);
    vi.spyOn(window, "matchMedia").mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn((event, listener) => {
        if (event === "change") {
          mediaListeners.set(query, listener as (event: MediaQueryListEvent) => void);
        }
      }),
      removeEventListener: vi.fn((event, listener) => {
        if (event === "change") {
          mediaListeners.delete(query);
        }
      }),
      dispatchEvent: vi.fn(),
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts open on desktop viewports", () => {
    const { result } = renderHookWithI18n(() => useSidebarLayout());
    expect(result.current.sidebarOpen).toBe(true);
  });

  it("starts closed on mobile viewports", () => {
    vi.mocked(layout.isMobileViewport).mockReturnValue(true);
    const { result } = renderHookWithI18n(() => useSidebarLayout());
    expect(result.current.sidebarOpen).toBe(false);
  });

  it("toggles and closes the sidebar", () => {
    const { result } = renderHookWithI18n(() => useSidebarLayout());

    act(() => {
      result.current.toggleSidebar();
    });
    expect(result.current.sidebarOpen).toBe(false);

    act(() => {
      result.current.toggleSidebar();
    });
    expect(result.current.sidebarOpen).toBe(true);

    act(() => {
      result.current.closeSidebar();
    });
    expect(result.current.sidebarOpen).toBe(false);
  });

  it("closes the sidebar on mobile only", () => {
    const { result } = renderHookWithI18n(() => useSidebarLayout());

    act(() => {
      result.current.closeSidebarOnMobile();
    });
    expect(result.current.sidebarOpen).toBe(true);

    vi.mocked(layout.isMobileViewport).mockReturnValue(true);
    act(() => {
      result.current.closeSidebarOnMobile();
    });
    expect(result.current.sidebarOpen).toBe(false);
  });

  it("closes the sidebar when the viewport crosses the mobile breakpoint", () => {
    const { result } = renderHookWithI18n(() => useSidebarLayout());
    const listener = mediaListeners.get(`(max-width: ${layout.MOBILE_BREAKPOINT}px)`);
    expect(listener).toBeTypeOf("function");

    act(() => {
      listener?.({ matches: true } as MediaQueryListEvent);
    });
    expect(result.current.sidebarOpen).toBe(false);
  });
});
