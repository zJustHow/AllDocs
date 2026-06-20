import { describe, expect, it } from "vitest";
import { getCachedMarkdownHtml, setCachedMarkdownHtml } from "./markdownCache";

describe("markdownCache", () => {
  it("stores and retrieves cached html by content and kind", () => {
    setCachedMarkdownHtml("# Title", "block", "<h1>Title</h1>");

    expect(getCachedMarkdownHtml("# Title", "block")).toBe("<h1>Title</h1>");
    expect(getCachedMarkdownHtml("# Title", "citations")).toBeNull();
  });

  it("evicts oldest entries after the cache limit", () => {
    for (let i = 0; i < 130; i += 1) {
      setCachedMarkdownHtml(`content-${i}`, "block", `<p>${i}</p>`);
    }

    expect(getCachedMarkdownHtml("content-0", "block")).toBeNull();
    expect(getCachedMarkdownHtml("content-129", "block")).toBe("<p>129</p>");
  });
});
