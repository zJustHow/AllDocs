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
    const { onOpenDocument } = renderMessage("See the diagram. {{embed:1}}", {
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
});
