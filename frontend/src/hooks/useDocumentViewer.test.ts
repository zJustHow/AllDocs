/** @vitest-environment jsdom */
import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderHookWithI18n, sampleDocument } from "./testUtils";
import { useDocumentViewer } from "./useDocumentViewer";
import { PANEL_CLOSE_MS } from "../layout";

describe("useDocumentViewer", () => {
  function renderViewer() {
    const registerRightPanel = vi.fn();
    const unregisterRightPanel = vi.fn();
    const hook = renderHookWithI18n(() =>
      useDocumentViewer({
        documents: [sampleDocument],
        registerRightPanel,
        unregisterRightPanel,
      }),
    );
    return { ...hook, registerRightPanel, unregisterRightPanel };
  }

  it("opens immediately and enriches document metadata", () => {
    const { result, registerRightPanel } = renderViewer();

    act(() => {
      result.current.openDocument({
        documentId: "doc-1",
        documentName: "Manual.pdf",
        page: 2,
      });
    });
    expect(result.current.viewerOpen).toBe(true);
    expect(registerRightPanel).toHaveBeenCalledWith("viewer");
    expect(result.current.viewerOpen).toBe(true);
    expect(result.current.viewerTarget).toMatchObject({
      documentId: "doc-1",
      page: 2,
      contentType: "application/pdf",
      pageCount: 8,
    });
  });

  it("keeps the viewer open when navigating to another target", () => {
    const { result, registerRightPanel } = renderViewer();

    act(() => {
      result.current.openDocument({
        documentId: "doc-1",
        documentName: "Manual.pdf",
        page: 1,
      });
    });
    registerRightPanel.mockClear();

    act(() => {
      result.current.openDocument({
        documentId: "doc-1",
        documentName: "Manual.pdf",
        page: 3,
      });
    });

    expect(registerRightPanel).not.toHaveBeenCalled();
    expect(result.current.viewerOpen).toBe(true);
    expect(result.current.viewerTarget?.page).toBe(3);
  });

  it("clears the viewer when closed", () => {
    const { result, unregisterRightPanel } = renderViewer();

    act(() => {
      result.current.openDocument({
        documentId: "doc-1",
        documentName: "Manual.pdf",
        page: 1,
      });
    });
    vi.useFakeTimers();
    act(() => {
      result.current.closeViewer();
    });

    expect(result.current.viewerOpen).toBe(false);
    expect(unregisterRightPanel).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(PANEL_CLOSE_MS);
    });

    expect(result.current.viewerTarget).toBeNull();
    expect(unregisterRightPanel).toHaveBeenCalledWith("viewer");
    vi.useRealTimers();
  });
});
