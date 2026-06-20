/** @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import DocumentViewer from "./DocumentViewer";
import { I18nProvider } from "./i18n";
import type { ViewerTarget } from "./citations";

const textTarget: ViewerTarget = {
  documentId: "doc-text",
  documentName: "notes.txt",
  contentType: "text/plain",
  page: null,
  section: null,
  regions: [],
};

function renderViewer(target: ViewerTarget = textTarget, onClose = vi.fn()) {
  return render(
    <I18nProvider>
      <DocumentViewer target={target} onClose={onClose} />
    </I18nProvider>,
  );
}

describe("DocumentViewer", () => {
  it("loads and renders plain text documents", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        text: async () => "Line one\nLine two",
      }),
    );

    renderViewer();

    expect(await screen.findByText(/Line one/)).toBeInTheDocument();
    expect(screen.getByText(/Line two/)).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("calls onClose from the header close button", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        text: async () => "content",
      }),
    );

    const user = userEvent.setup();
    const onClose = vi.fn();
    renderViewer(textTarget, onClose);

    await screen.findByText(/content/);
    await user.click(screen.getByRole("button", { name: /Close document preview|关闭/i }));

    expect(onClose).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it("shows an error banner when text loading fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
      }),
    );

    renderViewer();

    await waitFor(() => {
      expect(screen.getByText(/Failed to load document|无法加载文档/i)).toBeInTheDocument();
    });
    vi.unstubAllGlobals();
  });
});
