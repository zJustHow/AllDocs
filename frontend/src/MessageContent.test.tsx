/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
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

  it("renders streaming content without sentence-boundary embed splits", () => {
    renderMessage("Streaming answer [1].", {
      streaming: true,
      embeds: [embed],
    });

    expect(screen.getByText(/Streaming answer/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "[1]" })).toBeInTheDocument();
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
