/** @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DocumentViewer from "./DocumentViewer";
import { I18nProvider } from "./i18n";
import type { ViewerTarget } from "./citations";

let intersectionCallback: IntersectionObserverCallback | null = null;

beforeEach(() => {
  intersectionCallback = null;
  class IntersectionObserverMock implements IntersectionObserver {
    readonly root = null;
    readonly rootMargin = "";
    readonly thresholds = [];

    constructor(callback: IntersectionObserverCallback) {
      intersectionCallback = callback;
    }

    observe = vi.fn();
    disconnect = vi.fn();
    unobserve = vi.fn();
    takeRecords = vi.fn();
  }

  vi.stubGlobal("IntersectionObserver", IntersectionObserverMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

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

const pdfTarget: ViewerTarget = {
  documentId: "doc-pdf",
  documentName: "manual.pdf",
  contentType: "application/pdf",
  page: 1,
  pageCount: 3,
  section: null,
  regions: [{ page: 1, bbox: [0.1, 0.2, 0.3, 0.4] }],
};

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

  it("renders PDF toolbar controls", async () => {
    const user = userEvent.setup();
    renderViewer(pdfTarget);

    const pageInput = await screen.findByRole("textbox", { name: /Page number|页码/i });
    expect(pageInput).toHaveValue("1");
    expect(screen.getByText("/ 3")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Zoom in|放大/i }));
    expect(screen.getByText("125%")).toBeInTheDocument();
  });

  it("renders bbox highlight overlays after a PDF page loads", async () => {
    renderViewer(pdfTarget);

    const image = await screen.findByRole("img", { name: /manual.pdf p\.1/i });
    Object.defineProperty(image, "complete", { value: true, configurable: true });
    Object.defineProperty(image, "naturalWidth", { value: 800, configurable: true });
    Object.defineProperty(image, "naturalHeight", { value: 1200, configurable: true });
    Object.defineProperty(image, "offsetWidth", { value: 400, configurable: true });
    Object.defineProperty(image, "offsetHeight", { value: 600, configurable: true });
    image.dispatchEvent(new Event("load"));

    await waitFor(() => {
      expect(document.querySelector(".doc-viewer-highlight")).toBeInTheDocument();
    });
  });

  it("navigates PDF pages with arrow keys", async () => {
    renderViewer(pdfTarget);

    const pageInput = await screen.findByRole("textbox", { name: /Page number|页码/i });
    expect(pageInput).toHaveValue("1");

    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => {
      expect(pageInput).toHaveValue("2");
    });

    fireEvent.keyDown(window, { key: "ArrowLeft" });
    await waitFor(() => {
      expect(pageInput).toHaveValue("1");
    });
  });

  it("shows an error when a PDF page image fails to load", async () => {
    renderViewer(pdfTarget);

    const image = await screen.findByRole("img", { name: /manual.pdf p\.1/i });
    fireEvent.error(image);

    expect(await screen.findByText(/Failed to load document|无法加载文档/i)).toBeInTheDocument();
  });

  it("lazy-loads distant PDF pages when they intersect the viewport", async () => {
    renderViewer({ ...pdfTarget, page: 3, pageCount: 10 });

    await screen.findByRole("textbox", { name: /Page number|页码/i });
    const page8 = document.querySelector('[data-page="8"]') as HTMLElement;
    expect(page8.querySelector(".doc-viewer-page-placeholder")).toBeInTheDocument();

    intersectionCallback?.(
      [{ isIntersecting: true, target: page8 } as IntersectionObserverEntry],
      {} as IntersectionObserver,
    );

    await waitFor(() => {
      expect(page8.querySelector("img")).toBeInTheDocument();
    });
  });

  it("updates the current page while scrolling through the PDF", async () => {
    renderViewer({ ...pdfTarget, pageCount: 2 });

    const pageInput = await screen.findByRole("textbox", { name: /Page number|页码/i });
    await new Promise((resolve) => setTimeout(resolve, 100));

    const scrollEl = document.querySelector(".doc-viewer-scroll") as HTMLElement;
    const page1 = document.querySelector('[data-page="1"]') as HTMLElement;
    const page2 = document.querySelector('[data-page="2"]') as HTMLElement;

    Object.defineProperty(page1, "offsetTop", { value: 0, configurable: true });
    Object.defineProperty(page1, "offsetHeight", { value: 600, configurable: true });
    Object.defineProperty(page2, "offsetTop", { value: 600, configurable: true });
    Object.defineProperty(page2, "offsetHeight", { value: 600, configurable: true });
    Object.defineProperty(scrollEl, "scrollTop", { value: 500, writable: true, configurable: true });
    Object.defineProperty(scrollEl, "clientHeight", { value: 400, configurable: true });

    fireEvent.scroll(scrollEl);

    await waitFor(() => {
      expect(pageInput).toHaveValue("2");
    });
  });

  it("resets invalid page input on blur", async () => {
    const user = userEvent.setup();
    renderViewer(pdfTarget);

    const pageInput = await screen.findByRole("textbox", { name: /Page number|页码/i });
    await user.clear(pageInput);
    await user.type(pageInput, "abc");
    fireEvent.blur(pageInput);

    expect(pageInput).toHaveValue("1");
  });

  it("renders image previews for supported image documents", () => {
    renderViewer({
      documentId: "doc-img",
      documentName: "photo.png",
      contentType: "image/png",
      page: null,
      section: null,
      regions: [],
    });

    expect(screen.getByRole("img", { name: "photo.png" })).toHaveAttribute(
      "src",
      "/api/v1/documents/doc-img/file",
    );
  });

  it("shows unsupported preview messaging for unknown file types", () => {
    renderViewer({
      documentId: "doc-zip",
      documentName: "archive.zip",
      contentType: "application/zip",
      page: null,
      section: null,
      regions: [],
    });

    expect(
      screen.getByText(/Preview is not available for this format|不支持预览/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download original file|下载/i })).toHaveAttribute(
      "href",
      "/api/v1/documents/doc-zip/file",
    );
  });
});
