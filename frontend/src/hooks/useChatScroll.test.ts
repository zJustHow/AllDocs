/** @vitest-environment jsdom */
import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHookWithI18n } from "./testUtils";
import { useChatScroll } from "./useChatScroll";

describe("useChatScroll", () => {
  beforeEach(() => {
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      callback(0);
      return 1;
    });
    vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts without a scroll target", () => {
    const { result } = renderHookWithI18n(() => useChatScroll());
    expect(result.current.scrollTargetId).toBeNull();
  });

  it("registers and removes message refs", () => {
    const { result } = renderHookWithI18n(() => useChatScroll());
    const messageEl = document.createElement("article");

    act(() => {
      result.current.registerMessageRef("msg-1", messageEl);
    });

    act(() => {
      result.current.setScrollTargetId("msg-1");
    });

    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledWith({
      block: "start",
      behavior: "instant",
    });
    expect(result.current.scrollTargetId).toBeNull();
  });

  it("resets scroll, refs, and spacer on resetSpacer", () => {
    const { result } = renderHookWithI18n(() => useChatScroll());
    const container = document.createElement("div");
    const spacer = document.createElement("div");
    const messageEl = document.createElement("article");

    Object.defineProperty(container, "clientHeight", { value: 800, configurable: true });
    Object.defineProperty(messageEl, "getBoundingClientRect", {
      value: () => ({ height: 120 }),
      configurable: true,
    });

    container.scrollTop = 500;
    spacer.style.minHeight = "200px";

    act(() => {
      (result.current.chatAreaRef as { current: HTMLDivElement | null }).current = container;
      (result.current.spacerRef as { current: HTMLDivElement | null }).current = spacer;
      result.current.registerMessageRef("msg-1", messageEl);
      result.current.setScrollTargetId("msg-1");
    });

    expect(spacer.style.minHeight).not.toBe("");

    act(() => {
      result.current.resetSpacer();
    });

    expect(container.scrollTop).toBe(0);
    expect(spacer.style.minHeight).toBe("");

    act(() => {
      result.current.setScrollTargetId("msg-1");
    });
    expect(spacer.style.minHeight).toBe("");
  });
});
