/** @vitest-environment jsdom */
import { act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  deleteDocument,
  listDocuments,
  reindexDocument,
  setDocumentChatEnabled,
  uploadDocument,
} from "../api";
import { loadSupportedFormats } from "../fileTypes";
import { processingDocument, renderHookWithI18n, sampleDocument } from "./testUtils";
import { useDocuments } from "./useDocuments";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    listDocuments: vi.fn(),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
    reindexDocument: vi.fn(),
    setDocumentChatEnabled: vi.fn(),
  };
});

vi.mock("../fileTypes", async () => {
  const actual = await vi.importActual<typeof import("../fileTypes")>("../fileTypes");
  return {
    ...actual,
    loadSupportedFormats: vi.fn(),
  };
});

describe("useDocuments", () => {
  const setError = vi.fn();
  const confirm = vi.fn();

  beforeEach(() => {
    setError.mockReset();
    confirm.mockReset();
    vi.mocked(listDocuments).mockResolvedValue([sampleDocument]);
    vi.mocked(loadSupportedFormats).mockResolvedValue(undefined);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  function renderDocumentsHook() {
    return renderHookWithI18n(() => useDocuments({ setError, confirm, isAdmin: true }));
  }

  it("loads supported formats and selects ready documents on mount", async () => {
    const { result } = renderDocumentsHook();

    await waitFor(() => {
      expect(result.current.documents).toEqual([sampleDocument]);
    });

    expect(loadSupportedFormats).toHaveBeenCalled();
    expect(listDocuments).toHaveBeenCalled();
    expect(result.current.selectedDocIds).toEqual(["doc-1"]);
    expect(result.current.readyDocs).toEqual([sampleDocument]);
    expect(result.current.indexingDocs).toEqual([]);
  });

  it("toggles document chat availability via API", async () => {
    vi.mocked(setDocumentChatEnabled).mockResolvedValueOnce({
      ...sampleDocument,
      chat_enabled: false,
    });
    const { result } = renderDocumentsHook();

    await waitFor(() => {
      expect(result.current.selectedDocIds).toEqual(["doc-1"]);
    });

    await act(async () => {
      await result.current.toggleDoc("doc-1");
    });

    expect(setDocumentChatEnabled).toHaveBeenCalledWith("doc-1", false);
    expect(result.current.selectedDocIds).toEqual([]);
  });

  it("reports load failures through setError", async () => {
    vi.mocked(listDocuments).mockRejectedValueOnce(new Error("load failed"));
    renderDocumentsHook();

    await waitFor(() => {
      expect(setError).toHaveBeenCalledWith("Error: load failed");
    });
  });


  it("reports load failures through setError", async () => {
    const { result } = renderDocumentsHook();
    await waitFor(() => {
      expect(result.current.documents).toHaveLength(1);
    });

    const file = new File(["pdf"], "new.pdf", { type: "application/pdf" });
    vi.mocked(uploadDocument).mockResolvedValueOnce(sampleDocument);

    await act(async () => {
      await result.current.handleUpload(file);
    });

    expect(uploadDocument).toHaveBeenCalledWith(file);
    expect(setError).toHaveBeenCalledWith(null);
    expect(result.current.uploading).toBe(false);
    expect(listDocuments).toHaveBeenCalledTimes(2);
  });

  it("ignores null uploads", async () => {
    const { result } = renderDocumentsHook();
    await waitFor(() => {
      expect(result.current.documents).toHaveLength(1);
    });

    await act(async () => {
      await result.current.handleUpload(null);
    });

    expect(uploadDocument).not.toHaveBeenCalled();
  });

  it("deletes a document after confirmation", async () => {
    confirm.mockResolvedValueOnce(true);
    vi.mocked(listDocuments)
      .mockResolvedValueOnce([sampleDocument])
      .mockResolvedValueOnce([]);
    const { result } = renderDocumentsHook();
    await waitFor(() => {
      expect(result.current.selectedDocIds).toEqual(["doc-1"]);
    });

    await act(async () => {
      await result.current.handleDelete("doc-1");
    });

    expect(deleteDocument).toHaveBeenCalledWith("doc-1");
  });

  it("skips delete when confirmation is cancelled", async () => {
    confirm.mockResolvedValueOnce(false);
    const { result } = renderDocumentsHook();
    await waitFor(() => {
      expect(result.current.documents).toHaveLength(1);
    });

    await act(async () => {
      await result.current.handleDelete("doc-1");
    });

    expect(deleteDocument).not.toHaveBeenCalled();
  });

  it("reindexes a document after confirmation", async () => {
    confirm.mockResolvedValueOnce(true);
    vi.mocked(reindexDocument).mockResolvedValueOnce(processingDocument);
    const { result } = renderDocumentsHook();
    await waitFor(() => {
      expect(result.current.documents).toHaveLength(1);
    });

    await act(async () => {
      await result.current.handleReindex("doc-1");
    });

    expect(reindexDocument).toHaveBeenCalledWith("doc-1");
    expect(setError).toHaveBeenCalledWith(null);
  });
});
