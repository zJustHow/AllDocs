/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ProseBlock from "./ProseBlock";
import { citationPlaceholder } from "./citationPlaceholders";
import { I18nProvider } from "./i18n";
import type { Citation } from "./types";

const citation: Citation = {
  document_id: "doc-1",
  document_name: "Manual",
  page: 4,
  section: "Setup",
  snippet: "Press start.",
  regions: [],
};

function renderProse(content: string, onOpenDocument = vi.fn()) {
  return render(
    <I18nProvider>
      <ProseBlock content={content} citations={[citation]} onOpenDocument={onOpenDocument} />
    </I18nProvider>,
  );
}

describe("ProseBlock", () => {
  it("renders markdown without citation placeholders", () => {
    renderProse("## Heading\n\nParagraph text.");

    expect(screen.getByText("Heading")).toBeInTheDocument();
    expect(screen.getByText("Paragraph text.")).toBeInTheDocument();
  });

  it("renders citation buttons and opens the document on click", async () => {
    const user = userEvent.setup();
    const onOpenDocument = vi.fn();
    const content = `See ${citationPlaceholder(0)} for details.`;

    renderProse(content, onOpenDocument);

    const citationButton = screen.getByRole("button", { name: "[1]" });
    expect(citationButton).toHaveAttribute("title");

    await user.click(citationButton);

    expect(onOpenDocument).toHaveBeenCalledWith(
      expect.objectContaining({
        documentId: "doc-1",
        page: 4,
      }),
    );
  });
});
