/** @vitest-environment jsdom */
import { type ComponentProps } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Sidebar from "./Sidebar";
import { I18nProvider } from "./i18n";
import type { DocumentItem } from "./types";

const documents: DocumentItem[] = [
  {
    id: "doc-ready",
    name: "Manual.pdf",
    status: "ready",
    page_count: 12,
    ocr_pages: null,
    progress: 100,
    progress_message: null,
    error_message: null,
    chat_enabled: true,
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "doc-processing",
    name: "Guide.pdf",
    status: "processing",
    page_count: null,
    ocr_pages: 2,
    progress: 40,
    progress_message: "OCR page 2",
    error_message: null,
    chat_enabled: false,
    created_at: "2026-01-02T00:00:00Z",
  },
];

const statusLabel: Record<DocumentItem["status"], string> = {
  pending: "Pending",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
  deleting: "Deleting",
};

function renderSidebar(overrides: Partial<ComponentProps<typeof Sidebar>> = {}) {
  const onToggle = vi.fn();
  const onNewChat = vi.fn();
  const onUpload = vi.fn();
  const onToggleDoc = vi.fn();
  const onReindex = vi.fn();
  const onDelete = vi.fn();

  render(
    <I18nProvider>
      <Sidebar
        open
        documents={documents}
        readyCount={1}
        uploading={false}
        statusLabel={statusLabel}
        isAdmin
        onToggle={onToggle}
        onNewChat={onNewChat}
        onUpload={onUpload}
        onToggleDoc={onToggleDoc}
        onReindex={onReindex}
        onDelete={onDelete}
        {...overrides}
      />
    </I18nProvider>,
  );

  return { onToggle, onNewChat, onUpload, onToggleDoc, onReindex, onDelete };
}

describe("Sidebar", () => {
  it("renders documents and selection state", () => {
    renderSidebar();

    expect(screen.getByText("Manual.pdf")).toBeInTheDocument();
    expect(screen.getByText("Guide.pdf")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Manual.pdf/i })).toBeChecked();
    expect(screen.getByText(/OCR page 2/)).toBeInTheDocument();
  });

  it("starts a new chat from the sidebar action", async () => {
    const user = userEvent.setup();
    const { onNewChat } = renderSidebar();

    await user.click(screen.getByRole("button", { name: /New chat|新对话/i }));

    expect(onNewChat).toHaveBeenCalledTimes(1);
  });

  it("toggles ready documents and triggers reindex/delete actions", async () => {
    const user = userEvent.setup();
    const { onToggleDoc, onReindex, onDelete } = renderSidebar();

    await user.click(screen.getByRole("checkbox", { name: /Manual.pdf/i }));
    expect(onToggleDoc).toHaveBeenCalledWith("doc-ready");

    await user.click(screen.getAllByRole("button", { name: /Reindex|重新索引/i })[0]!);
    expect(onReindex).toHaveBeenCalledWith("doc-ready");

    await user.click(screen.getAllByRole("button", { name: /Delete|删除/i })[0]!);
    expect(onDelete).toHaveBeenCalledWith("doc-ready");
  });

  it("shows pending and failed document states", () => {
    renderSidebar({
      documents: [
        {
          id: "doc-pending",
          name: "Pending.pdf",
          status: "pending",
          page_count: null,
          ocr_pages: null,
          progress: 0,
          progress_message: null,
          error_message: null,
          chat_enabled: false,
          created_at: "2026-01-03T00:00:00Z",
        },
        {
          id: "doc-failed",
          name: "Broken.pdf",
          status: "failed",
          page_count: null,
          ocr_pages: null,
          progress: 0,
          progress_message: null,
          error_message: "Index failed",
          chat_enabled: false,
          created_at: "2026-01-04T00:00:00Z",
        },
        {
          id: "doc-deleting",
          name: "Removing.pdf",
          status: "deleting",
          page_count: null,
          ocr_pages: null,
          progress: 0,
          progress_message: null,
          error_message: null,
          chat_enabled: false,
          created_at: "2026-01-05T00:00:00Z",
        },
      ],
      readyCount: 0,
    });

    expect(screen.getByText("Pending.pdf")).toBeInTheDocument();
    expect(screen.getByText("Index failed")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Reindex|重新索引/i }).length).toBeGreaterThan(0);
    const deleteButtons = screen.getAllByRole("button", { name: /Delete|删除/i });
    expect(deleteButtons.some((button) => button.hasAttribute("disabled"))).toBe(true);
  });

  it("shows an empty library message and handles upload and collapse", async () => {
    const user = userEvent.setup();
    const { onUpload, onToggle } = renderSidebar({
      documents: [],
      readyCount: 0,
    });

    expect(screen.getByText(/No documents yet|暂无文档/i)).toBeInTheDocument();

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["bytes"], "Guide.pdf", { type: "application/pdf" });
    await user.upload(fileInput, file);
    expect(onUpload).toHaveBeenCalledWith(file);

    await user.click(screen.getByRole("button", { name: /Collapse sidebar|收起侧栏/i }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
