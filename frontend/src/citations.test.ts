import { describe, expect, it } from "vitest";
import {
  citationToViewerTarget,
  embedToViewerTarget,
  formatCitationLabel,
  formatCitationSnippetExcerpt,
  formatCitationTooltip,
  isOrphanInlineSuffix,
  isTrailingPunctuationOnly,
  proseSegmentsHaveContent,
  segmentsDisplayText,
  segmentsToMarkdownSource,
  splitMessageWithCitations,
} from "./citations";
import { citationPlaceholder } from "./citationPlaceholders";
import type { Citation, MessageEmbed } from "./types";

function makeCitation(overrides: Partial<Citation> = {}): Citation {
  return {
    document_id: "doc-1",
    document_name: "Manual",
    page: 3,
    section: "Setup",
    snippet: "Press the start button.",
    score: 0.9,
    regions: [{ page: 3, bbox: [0.1, 0.2, 0.3, 0.4] }],
    ...overrides,
  };
}

describe("formatCitationLabel", () => {
  it("uses one-based display index", () => {
    expect(formatCitationLabel(0)).toBe("[1]");
    expect(formatCitationLabel(2)).toBe("[3]");
  });
});

describe("formatCitationSnippetExcerpt", () => {
  it("adds ellipsis when snippet lacks edge punctuation", () => {
    expect(formatCitationSnippetExcerpt("Press start")).toBe("...Press start...");
  });

  it("keeps existing punctuation at both edges", () => {
    expect(formatCitationSnippetExcerpt("。已标定。")).toBe("。已标定。");
  });

  it("returns empty string unchanged", () => {
    expect(formatCitationSnippetExcerpt("   ")).toBe("");
  });
});

describe("formatCitationTooltip", () => {
  it("includes document, page hint, section, and excerpt", () => {
    const tooltip = formatCitationTooltip(makeCitation(), " p.3");

    expect(tooltip).toContain("Manual p.3 · Setup");
    expect(tooltip).toContain("Press the start button.");
  });
});

describe("viewer target mappers", () => {
  it("maps citation fields to viewer target", () => {
    const citation = makeCitation();
    expect(citationToViewerTarget(citation)).toEqual({
      documentId: "doc-1",
      documentName: "Manual",
      page: 3,
      section: "Setup",
      snippet: "Press the start button.",
      regions: [{ page: 3, bbox: [0.1, 0.2, 0.3, 0.4] }],
    });
  });

  it("maps embed fields to viewer target", () => {
    const embed: MessageEmbed = {
      ref: 1,
      document_id: "doc-2",
      document_name: "Guide",
      page: 5,
      type: "figure",
      url: "/img.png",
      caption: "Figure 1",
      regions: [{ page: 5, bbox: [0, 0, 1, 1] }],
    };

    expect(embedToViewerTarget(embed)).toEqual({
      documentId: "doc-2",
      documentName: "Guide",
      page: 5,
      section: "Figure 1",
      regions: [{ page: 5, bbox: [0, 0, 1, 1] }],
    });
  });
});

describe("splitMessageWithCitations", () => {
  const citations = [
    makeCitation({ snippet: "first" }),
    makeCitation({ page: 7, snippet: "second" }),
  ];

  it("strips inline citation markers when no citations or embeds are provided", () => {
    const segments = splitMessageWithCitations("See [1] and [2].", [], {
      hideUnmatched: true,
    });

    expect(segments).toEqual([{ type: "text", value: "See  and ." }]);
  });

  it("resolves numeric citation markers", () => {
    const segments = splitMessageWithCitations("Refer to [2].", citations, {
      hideUnmatched: true,
    });

    expect(segments.some((s) => s.type === "citation" && s.index === 1)).toBe(true);
  });

  it("keeps non-numeric bracket text as plain prose", () => {
    const segments = splitMessageWithCitations("Press [START] then [1].", citations, {
      hideUnmatched: true,
    });

    expect(segments).toEqual([
      { type: "text", value: "Press [START] then " },
      {
        type: "citation",
        value: "[1].",
        citation: citations[0],
        index: 0,
      },
    ]);
  });

  it("hides unmatched citation tokens when configured", () => {
    const segments = splitMessageWithCitations("Unknown [9].", citations, {
      hideUnmatched: true,
    });

    expect(segments.every((s) => s.type !== "citation")).toBe(true);
  });

  it("keeps unmatched citation tokens as text when not hiding", () => {
    const segments = splitMessageWithCitations("[9]", citations, {
      hideUnmatched: false,
    });

    expect(segments).toEqual([{ type: "text", value: "[9]" }]);
  });

  it("inserts embed segments after the aligned sentence", () => {
    const embed: MessageEmbed = {
      ref: 2,
      sentence_index: 0,
      document_id: "doc-1",
      page: 1,
      type: "figure",
      url: "/x.png",
      regions: [],
    };

    const segments = splitMessageWithCitations("See the diagram.", citations, {
      hideUnmatched: true,
      embeds: [embed],
    });

    expect(segments.some((s) => s.type === "embed" && s.embed.ref === 2)).toBe(true);
  });

  it("defers embed placement during streaming until the embed list arrives", () => {
    const embed: MessageEmbed = {
      ref: 1,
      sentence_index: 0,
      document_id: "doc-1",
      page: 1,
      type: "figure",
      url: "/x.png",
      regions: [],
    };

    const segments = splitMessageWithCitations("See the diagram.", citations, {
      hideUnmatched: true,
      streaming: true,
    });

    expect(segments.every((segment) => segment.type !== "embed")).toBe(true);
  });

  it("places embeds during streaming once the embed list is known", () => {
    const embed: MessageEmbed = {
      ref: 1,
      sentence_index: 0,
      document_id: "doc-1",
      page: 1,
      type: "figure",
      url: "/x.png",
      regions: [],
    };

    const segments = splitMessageWithCitations("See the diagram.", citations, {
      hideUnmatched: true,
      embeds: [embed],
      streaming: true,
    });

    expect(segments.some((segment) => segment.type === "embed")).toBe(true);
  });

  it("returns original content when every citation token is hidden", () => {
    const segments = splitMessageWithCitations("[9]", citations, {
      hideUnmatched: true,
    });

    expect(segments).toEqual([{ type: "text", value: "[9]" }]);
  });

  it("absorbs trailing punctuation before trailing embed segments", () => {
    const embed: MessageEmbed = {
      ref: 1,
      sentence_index: 0,
      document_id: "doc-1",
      page: 1,
      type: "figure",
      url: "/x.png",
      regions: [],
    };

    const segments = splitMessageWithCitations("See [1].", citations, {
      hideUnmatched: true,
      embeds: [embed],
    });

    const trailingText = segments.filter((segment) => segment.type === "text").at(-1)?.value ?? "";
    expect(trailingText).not.toMatch(/^[\s,.;:!?。，；：！？…、）】」』《"''']+$/);
  });

  it("absorbs trailing punctuation into the preceding citation segment", () => {
    const embed: MessageEmbed = {
      ref: 1,
      sentence_index: 0,
      document_id: "doc-1",
      page: 1,
      type: "figure",
      url: "/x.png",
      regions: [],
    };

    const segments = splitMessageWithCitations("See [1].", citations, {
      hideUnmatched: true,
      embeds: [embed],
    });

    const citationSegment = segments.find((segment) => segment.type === "citation");
    expect(citationSegment?.value).toBe("[1].");
  });

  it("does not split text on sentence boundaries in streaming mode", () => {
    const segments = splitMessageWithCitations("Line one. Line two [1].", citations, {
      hideUnmatched: true,
      streaming: true,
    });

    const textSegments = segments.filter((s) => s.type === "text");
    expect(textSegments[0]?.value).toBe("Line one. Line two ");
    expect(segments.some((s) => s.type === "citation")).toBe(true);
  });
});

describe("segment helpers", () => {
  it("detects trailing punctuation-only text", () => {
    expect(isTrailingPunctuationOnly("。")).toBe(true);
    expect(isTrailingPunctuationOnly("word")).toBe(false);
  });

  it("detects orphan inline suffix segments", () => {
    expect(isOrphanInlineSuffix([{ type: "text", value: " [3]" }])).toBe(true);
    expect(
      isOrphanInlineSuffix([{ type: "text", value: "complete sentence." }]),
    ).toBe(false);
  });

  it("joins display text from text and citation segments", () => {
    const text = segmentsDisplayText([
      { type: "text", value: "Hello " },
      { type: "citation", value: "[1]", citation: makeCitation(), index: 0 },
    ]);

    expect(text).toBe("Hello [1]");
  });

  it("ignores embed segments when joining display text", () => {
    const text = segmentsDisplayText([
      { type: "text", value: "See " },
      {
        type: "embed",
        embed: {
          ref: 1,
          sentence_index: 0,
          document_id: "doc-1",
          page: 1,
          type: "figure",
          url: "/x.png",
          regions: [],
        },
      },
    ]);

    expect(text).toBe("See ");
  });

  it("builds markdown source with citation placeholders", () => {
    const md = segmentsToMarkdownSource([
      { type: "text", value: "See " },
      { type: "citation", value: "[1]", citation: makeCitation(), index: 0 },
    ]);

    expect(md).toBe(`See ${citationPlaceholder(0)}`);
  });

  it("reports whether prose segments have visible content", () => {
    expect(proseSegmentsHaveContent([{ type: "text", value: "   " }])).toBe(false);
    expect(
      proseSegmentsHaveContent([
        { type: "citation", value: "[1]", citation: makeCitation(), index: 0 },
      ]),
    ).toBe(true);
    expect(proseSegmentsHaveContent([{ type: "text", value: "Hi" }])).toBe(true);
    expect(
      proseSegmentsHaveContent([
        {
          type: "embed",
          embed: {
            ref: 1,
            sentence_index: 0,
            document_id: "doc-1",
            page: 1,
            type: "figure",
            url: "/x.png",
            regions: [],
          },
        },
      ]),
    ).toBe(false);
  });
});
