import { describe, expect, it } from "vitest";
import {
  buildFallbackPreviewModes,
  buildFallbackUploadAccept,
  embedDedupeKey,
  stripInlineMarkers,
} from "./contract";
import type { MessageEmbed } from "../types";

describe("stripInlineMarkers", () => {
  it("removes inline citation and embed markers", () => {
    expect(stripInlineMarkers("Text [1] and [2] end.")).toBe("Text  and  end.");
  });
});

describe("embedDedupeKey", () => {
  const base: MessageEmbed = {
    ref: 1,
    document_id: "doc-1",
    page: 2,
    type: "figure",
    url: "/a.png",
    regions: [],
  };

  it("prefers content hash when present", () => {
    expect(embedDedupeKey({ ...base, content_hash: "abc" })).toBe("hash:abc");
  });

  it("falls back to asset id, url, then page key", () => {
    expect(embedDedupeKey({ ...base, asset_id: "asset-1" })).toBe("asset:asset-1");
    expect(embedDedupeKey(base)).toBe("url:/a.png");
    expect(embedDedupeKey({ ...base, url: "" })).toBe("page:doc-1:2");
  });
});

describe("fallback file format helpers", () => {
  it("builds upload accept from shared contract", () => {
    const accept = buildFallbackUploadAccept();
    expect(accept).toContain(".pdf");
    expect(accept).toContain("application/pdf");
  });

  it("builds preview mode map from shared contract", () => {
    const modes = buildFallbackPreviewModes();
    expect(modes[".pdf"]).toBe("pdf");
  });
});
