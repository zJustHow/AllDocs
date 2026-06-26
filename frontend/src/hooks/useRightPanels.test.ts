/** @vitest-environment jsdom */
import { act } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderHookWithI18n } from "./testUtils";
import { useRightPanels } from "./useRightPanels";

describe("useRightPanels", () => {
  it("starts with an empty panel order", () => {
    const { result } = renderHookWithI18n(() => useRightPanels());

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

  it("unregisters arbitrary panels", () => {
    const { result } = renderHookWithI18n(() => useRightPanels());

    act(() => {
      result.current.registerRightPanel("viewer");
      result.current.unregisterRightPanel("viewer");
    });

    expect(result.current.rightPanelOrder).toEqual([]);
  });
});
