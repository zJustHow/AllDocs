/** @vitest-environment jsdom */
import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PANEL_CLOSE_MS } from "../layout";
import { renderHookWithI18n } from "./testUtils";
import { useRightPanels } from "./useRightPanels";

describe("useRightPanels", () => {
  it("starts with settings closed and an empty panel order", () => {
    const { result } = renderHookWithI18n(() => useRightPanels());

    expect(result.current.settingsOpen).toBe(false);
    expect(result.current.rightPanelOrder).toEqual([]);
  });

  it("registers a panel only once", () => {
    const { result } = renderHookWithI18n(() => useRightPanels());

    act(() => {
      result.current.registerRightPanel("viewer");
      result.current.registerRightPanel("viewer");
    });

    expect(result.current.rightPanelOrder).toEqual(["viewer"]);
  });

  it("toggles settings open and closed while updating panel order", () => {
    vi.useFakeTimers();
    const { result } = renderHookWithI18n(() => useRightPanels());

    act(() => {
      result.current.toggleSettings();
    });
    expect(result.current.settingsOpen).toBe(true);
    expect(result.current.rightPanelOrder).toContain("settings");

    act(() => {
      result.current.toggleSettings();
    });
    expect(result.current.settingsOpen).toBe(false);
    expect(result.current.rightPanelOrder).toContain("settings");
    act(() => {
      vi.advanceTimersByTime(PANEL_CLOSE_MS);
    });
    expect(result.current.rightPanelOrder).not.toContain("settings");
    vi.useRealTimers();
  });

  it("closes settings and unregisters the panel", () => {
    vi.useFakeTimers();
    const { result } = renderHookWithI18n(() => useRightPanels());

    act(() => {
      result.current.toggleSettings();
    });
    act(() => {
      result.current.closeSettings();
    });

    expect(result.current.settingsOpen).toBe(false);
    expect(result.current.rightPanelOrder).toContain("settings");
    act(() => {
      vi.advanceTimersByTime(PANEL_CLOSE_MS);
    });
    expect(result.current.rightPanelOrder).not.toContain("settings");
    vi.useRealTimers();
  });

  it("unregisters arbitrary panels", () => {
    const { result } = renderHookWithI18n(() => useRightPanels());

    act(() => {
      result.current.registerRightPanel("viewer");
      result.current.unregisterRightPanel("viewer");
    });

    expect(result.current.rightPanelOrder).toEqual([]);
  });
});
