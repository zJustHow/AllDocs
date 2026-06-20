/** @vitest-environment jsdom */
import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHookWithI18n, sampleDocument } from "./testUtils";
import { useDocumentViewer } from "./useDocumentViewer";

describe("useDocumentViewer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      callback(0);
      return 1;
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

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

  it("opens a document and enriches metadata from the library", () => {
    const { result, registerRightPanel } = renderViewer();

    act(() => {
      result.current.openDocument({
        documentId: "doc-1",
        documentName: "Manual.pdf",
        page: 2,
      });
    });

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

  it("clears the viewer immediately when requested", () => {
    const { result, unregisterRightPanel } = renderViewer();

    act(() => {
      result.current.openDocument({
        documentId: "doc-1",
        documentName: "Manual.pdf",
        page: 1,
      });
    });
    act(() => {
      result.current.closeViewer(true);
    });

    expect(result.current.viewerOpen).toBe(false);
    expect(result.current.viewerTarget).toBeNull();
    expect(unregisterRightPanel).toHaveBeenCalledWith("viewer");
  });

  it("defers clearing the viewer until the close animation finishes", () => {
    const { result, unregisterRightPanel } = renderViewer();

    act(() => {
      result.current.openDocument({
        documentId: "doc-1",
        documentName: "Manual.pdf",
        page: 1,
      });
    });
    act(() => {
      result.current.closeViewer();
    });

    expect(result.current.viewerOpen).toBe(false);
    expect(result.current.viewerTarget).not.toBeNull();
    expect(unregisterRightPanel).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(320);
    });

    expect(result.current.viewerTarget).toBeNull();
    expect(unregisterRightPanel).toHaveBeenCalledWith("viewer");
  });
});
