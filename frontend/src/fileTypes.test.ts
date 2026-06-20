import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("fileTypes", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses fallback preview modes before API load", async () => {
    const { getPreviewMode } = await import("./fileTypes");

    expect(getPreviewMode("manual.pdf")).toBe("pdf");
    expect(getPreviewMode("photo.png", "image/png")).toBe("image");
    expect(getPreviewMode("notes.txt", "text/plain")).toBe("text");
    expect(getPreviewMode("archive.zip")).toBe("unsupported");
    expect(getPreviewMode("noextension", "image/png")).toBe("image");
  });

  it("loads supported formats from API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          upload_accept: ".custom",
          preview_modes: { ".custom": "text" },
        }),
      }),
    );

    const { loadSupportedFormats, getUploadAccept, getPreviewMode } = await import(
      "./fileTypes"
    );

    await loadSupportedFormats();

    expect(getUploadAccept()).toBe(".custom");
    expect(getPreviewMode("data.custom")).toBe("text");
  });

  it("keeps fallback values when API request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    const { loadSupportedFormats, getUploadAccept, getPreviewMode } = await import(
      "./fileTypes"
    );

    await loadSupportedFormats();

    expect(getUploadAccept()).toContain(".pdf");
    expect(getPreviewMode("manual.pdf")).toBe("pdf");
  });
});
