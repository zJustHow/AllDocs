/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import MessageContent from "./MessageContent";
import { I18nProvider } from "./i18n";
import type { Citation, MessageEmbed } from "./types";

const citation: Citation = {
  document_id: "doc-1",
  document_name: "Manual",
  page: 2,
  section: null,
  snippet: "Start the robot.",
  regions: [],
};

const embed: MessageEmbed = {
  ref: 1,
  sentence_index: 0,
  document_id: "doc-1",
  document_name: "Manual",
  page: 2,
  type: "figure",
  url: "/embed.png",
  caption: "Figure 1",
  regions: [],
};

function renderMessage(
  content: string,
  options?: {
    citations?: Citation[];
    embeds?: MessageEmbed[];
    onOpenDocument?: ReturnType<typeof vi.fn>;
  },
) {
  const onOpenDocument = options?.onOpenDocument ?? vi.fn();

  render(
    <I18nProvider>
      <MessageContent
        content={content}
        citations={options?.citations ?? [citation]}
        embeds={options?.embeds}
        onOpenDocument={onOpenDocument}
      />
    </I18nProvider>,
  );

  return { onOpenDocument };
}

describe("MessageContent", () => {
  it("renders prose with inline citations", () => {
    renderMessage("Follow step [1] carefully.");

    expect(screen.getByRole("button", { name: "[1]" })).toBeInTheDocument();
    expect(screen.getByText(/Follow step/i)).toBeInTheDocument();
  });

  it("renders embed figures and opens the document from caption link", async () => {
    const user = userEvent.setup();
    const { onOpenDocument } = renderMessage("See the diagram.", {
      embeds: [embed],
    });

    expect(screen.getByRole("img", { name: /Figure 1/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Figure 1/i }));

    expect(onOpenDocument).toHaveBeenCalledWith(
      expect.objectContaining({
        documentId: "doc-1",
        page: 2,
      }),
    );
  });

  it("returns null for blank content", () => {
    const { container } = render(
      <I18nProvider>
        <MessageContent content="   " onOpenDocument={vi.fn()} />
      </I18nProvider>,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("renders table embeds with table layout classes", () => {
    renderMessage("See the table.", {
      embeds: [{ ...embed, type: "table", caption: "Table 1" }],
    });

    expect(document.querySelector(".answer-media-block--table")).toBeInTheDocument();
    expect(document.querySelector(".answer-embed--table")).toBeInTheDocument();
  });

  it("places each table on its own row and groups figures on one row", () => {
    renderMessage("See the assets.", {
      embeds: [
        { ...embed, ref: 1, caption: "Figure 1", type: "figure", sentence_index: 0 },
        {
          ...embed,
          ref: 2,
          caption: "Table 1",
          type: "table",
          url: "/table1.png",
          sentence_index: 0,
        },
        { ...embed, ref: 3, caption: "Figure 2", type: "figure", url: "/fig2.png", sentence_index: 0 },
        {
          ...embed,
          ref: 4,
          caption: "Table 2",
          type: "table",
          url: "/table2.png",
          sentence_index: 0,
        },
      ],
    });

    const mediaBlocks = document.querySelectorAll(".answer-media-figures");
    expect(mediaBlocks).toHaveLength(3);

    expect(mediaBlocks[0]).not.toHaveClass("answer-media-block--table");
    expect(mediaBlocks[0].querySelectorAll(".answer-embed--figure")).toHaveLength(2);

    expect(mediaBlocks[1]).toHaveClass("answer-media-block--table");
    expect(mediaBlocks[1].querySelectorAll(".answer-embed--table")).toHaveLength(1);
    expect(screen.getByRole("img", { name: /Table 1/i })).toBeInTheDocument();

    expect(mediaBlocks[2]).toHaveClass("answer-media-block--table");
    expect(mediaBlocks[2].querySelectorAll(".answer-embed--table")).toHaveLength(1);
    expect(screen.getByRole("img", { name: /Table 2/i })).toBeInTheDocument();
  });

  it("opens the image lightbox from the embed preview", async () => {
    const user = userEvent.setup();
    renderMessage("See the diagram.", { embeds: [embed] });

    await user.click(screen.getByRole("button", { name: /View enlarged|查看大图/i }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("uses the document name when an embed has no caption", () => {
    renderMessage("See the figure.", {
      embeds: [{ ...embed, caption: undefined }],
    });

    expect(screen.getByRole("button", { name: /\[1\].*Manual/i })).toBeInTheDocument();
  });

  it("renders streaming content without embeds until the embed list arrives", () => {
    renderMessage("Streaming answer [1].", {
      streaming: true,
    });

    expect(screen.getByText(/Streaming answer/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "[1]" })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Figure 1/i })).not.toBeInTheDocument();
  });

  it("places embeds during streaming once the embed list is known", () => {
    renderMessage("See the diagram.", {
      streaming: true,
      embeds: [embed],
    });

    expect(screen.getByText(/See the diagram/i)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Figure 1/i })).toBeInTheDocument();
    expect(
      document.querySelector(".answer-embed-image-placeholder"),
    ).toBeInTheDocument();
  });

  it("shows the loaded image after the preview finishes loading", () => {
    renderMessage("See the diagram.", { embeds: [embed] });

    const image = screen.getByRole("img", { name: /Figure 1/i });
    fireEvent.load(image);

    expect(
      document.querySelector(".answer-embed-image-placeholder"),
    ).not.toBeInTheDocument();
    expect(image).not.toHaveClass("answer-embed-image--hidden");
  });

  it("merges orphan trailing citation suffixes into the preceding prose block", () => {
    renderMessage("See the diagram [1].", {
      embeds: [{ ...embed, sentence_index: 0 }],
      citations: [citation],
    });

    expect(screen.getByRole("img", { name: /Figure 1/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "[1]" })).toBeInTheDocument();
  });
});
