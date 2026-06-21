/** @vitest-environment jsdom */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamHandlers } from "./api";
import App from "./App";
import { I18nProvider } from "./i18n";

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 180,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        start: index * 180,
        key: String(index),
      })),
    measureElement: vi.fn(),
    measure: vi.fn(),
    scrollToIndex: vi.fn(),
  }),
}));

const listDocuments = vi.fn();
const loadSupportedFormats = vi.fn();
const streamChat = vi.fn();
const uploadDocument = vi.fn();
const deleteDocument = vi.fn();
const reindexDocument = vi.fn();
const createVoiceSocket = vi.fn();

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    listDocuments: (...args: Parameters<typeof listDocuments>) => listDocuments(...args),
    streamChat: (...args: Parameters<typeof streamChat>) => streamChat(...args),
    uploadDocument: (...args: Parameters<typeof uploadDocument>) => uploadDocument(...args),
    deleteDocument: (...args: Parameters<typeof deleteDocument>) => deleteDocument(...args),
    reindexDocument: (...args: Parameters<typeof reindexDocument>) =>
      reindexDocument(...args),
    createVoiceSocket: (...args: Parameters<typeof createVoiceSocket>) =>
      createVoiceSocket(...args),
  };
});

vi.mock("./fileTypes", async () => {
  const actual = await vi.importActual<typeof import("./fileTypes")>("./fileTypes");
  return {
    ...actual,
    loadSupportedFormats: (...args: Parameters<typeof loadSupportedFormats>) =>
      loadSupportedFormats(...args),
  };
});

const sampleDocuments = [
  {
    id: "doc-1",
    name: "Manual.pdf",
    status: "ready" as const,
    page_count: 8,
    ocr_pages: null,
    progress: 100,
    progress_message: null,
    error_message: null,
    created_at: "2026-01-01T00:00:00Z",
  },
];

type MockWebSocket = {
  readyState: number;
  send: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  onopen: (() => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: (() => void) | null;
  onclose: (() => void) | null;
};

let activeVoiceSocket: MockWebSocket | null = null;

function createMockWebSocket(): MockWebSocket {
  const ws: MockWebSocket = {
    readyState: 0,
    send: vi.fn(),
    close: vi.fn(),
    onopen: null,
    onmessage: null,
    onerror: null,
    onclose: null,
  };
  queueMicrotask(() => {
    ws.readyState = 1;
    ws.onopen?.();
  });
  return ws;
}

function renderApp() {
  return render(
    <I18nProvider>
      <App />
    </I18nProvider>,
  );
}

function getRightPanelDomOrder(): Array<"settings" | "viewer"> {
  const app = document.querySelector(".app");
  if (!app) return [];
  return Array.from(app.children)
    .filter(
      (el) =>
        el.classList.contains("settings-panel-slot") ||
        el.classList.contains("doc-viewer-slot"),
    )
    .map((el) =>
      el.classList.contains("settings-panel-slot") ? "settings" : "viewer",
    );
}

async function openCitationFromChat(user: ReturnType<typeof userEvent.setup>) {
  streamChat.mockImplementation(async (_message, _sessionId, _docIds, handlers: StreamHandlers) => {
    handlers.onDone({
      sessionId: "session-1",
      content: "See [1] for the alarm reset steps.",
      citations: [
        {
          document_id: "doc-1",
          document_name: "Manual.pdf",
          page: 2,
          section: null,
          snippet: "Reset alarm E-204.",
          regions: [],
        },
      ],
      embeds: [],
      language: "en",
    });
  });

  await user.type(screen.getByRole("textbox"), "Alarm help");
  await user.click(screen.getByRole("button", { name: /Send|发送/i }));
  await user.click(await screen.findByRole("button", { name: "[1]" }));
  await screen.findByRole("button", { name: /Close document preview|关闭/i });
  await waitFor(() => {
    expect(document.querySelector(".doc-viewer-slot.is-open")).toBeInTheDocument();
  });
}

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    activeVoiceSocket = null;
    listDocuments.mockResolvedValue(sampleDocuments);
    loadSupportedFormats.mockResolvedValue(undefined);
    uploadDocument.mockResolvedValue(sampleDocuments[0]);
    deleteDocument.mockResolvedValue(undefined);
    reindexDocument.mockResolvedValue(sampleDocuments[0]);
    streamChat.mockImplementation(async (_message, _sessionId, _docIds, handlers: StreamHandlers) => {
      handlers.onDelta("Partial ");
      handlers.onDelta("answer");
      handlers.onDone({
        sessionId: "session-1",
        content: "Partial answer",
        citations: [],
        embeds: [],
        language: "en",
      });
    });
    createVoiceSocket.mockImplementation(() => {
      activeVoiceSocket = createMockWebSocket();
      return activeVoiceSocket as unknown as WebSocket;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ groups: [] }),
      }),
    );
    vi.stubGlobal("navigator", {
      ...globalThis.navigator,
      language: "en-US",
      mediaDevices: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }],
        }),
      },
    });
    vi.stubGlobal(
      "MediaRecorder",
      class MockMediaRecorder {
        static isTypeSupported = vi.fn().mockReturnValue(true);
        mimeType = "audio/webm";
        state = "inactive";
        ondataavailable: ((event: { data: Blob }) => void) | null = null;
        onstop: (() => void) | null = null;

        constructor(_stream: MediaStream) {}

        start() {
          this.state = "recording";
        }

        requestData() {
          this.ondataavailable?.({
            data: new Blob(["x".repeat(600)], { type: "audio/webm" }),
          });
        }

        stop() {
          this.state = "inactive";
          this.onstop?.();
        }
      },
    );
  });

  it("loads documents and renders the main shell", async () => {
    renderApp();

    expect(await screen.findByText("Manual.pdf")).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /New chat|新对话/i })).toBeInTheDocument();
    expect(listDocuments).toHaveBeenCalled();
    expect(loadSupportedFormats).toHaveBeenCalled();
  });

  it("opens the settings panel from the header action", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Open settings|打开设置/i }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Settings|系统设置/i })).toBeInTheDocument();
  });

  it("hides the settings button while the panel is open", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    const settingsButton = screen.getByRole("button", { name: /Open settings|打开设置/i });

    expect(settingsButton.classList.contains("hidden")).toBe(false);

    await user.click(settingsButton);

    await screen.findByRole("dialog");
    expect(document.querySelector(".settings-overlay.visible")).toBeInTheDocument();
    expect(document.querySelector(".settings-panel.open")).toBeInTheDocument();
    expect(settingsButton).toHaveAttribute("aria-hidden", "true");
    expect(settingsButton.classList.contains("hidden")).toBe(true);
  });

  it("closes the settings panel when the overlay is clicked", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Open settings|打开设置/i }));
    await screen.findByRole("dialog");

    await user.click(document.querySelector(".settings-overlay") as HTMLElement);

    expect(document.querySelector(".settings-panel.open")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { hidden: true })).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("button", { name: /Open settings|打开设置/i })).toBeInTheDocument();
  });

  it("closes the settings panel from the header close button", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Open settings|打开设置/i }));
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: /Close dialog|关闭对话框/i }));

    expect(document.querySelector(".settings-panel.open")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open settings|打开设置/i })).toBeInTheDocument();
  });

  it("closes the settings panel from the footer cancel button", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Open settings|打开设置/i }));
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: /Cancel|取消/i }));

    expect(document.querySelector(".settings-panel.open")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open settings|打开设置/i })).toBeInTheDocument();
  });

  it("closes the settings panel on Escape", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Open settings|打开设置/i }));
    await screen.findByRole("dialog");

    await user.keyboard("{Escape}");

    expect(document.querySelector(".settings-panel.open")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open settings|打开设置/i })).toBeInTheDocument();
  });

  it("keeps the settings panel mounted while collapsed", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    expect(document.querySelector(".settings-panel.collapsed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Open settings|打开设置/i }));
    await screen.findByRole("dialog");
    expect(document.querySelector(".settings-panel.open")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(document.querySelector(".settings-panel.collapsed")).toBeInTheDocument();
    expect(document.querySelector(".settings-panel")).toBeInTheDocument();
  });

  it("closes settings when the header button is toggled again", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    const settingsButton = screen.getByRole("button", { name: /Open settings|打开设置/i });
    await user.click(settingsButton);
    await screen.findByRole("dialog");

    fireEvent.click(settingsButton);

    expect(document.querySelector(".settings-panel.open")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open settings|打开设置/i })).toBeInTheDocument();
  });

  it("starts a new chat and clears the transcript", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /New chat|新对话/i }));

    expect(screen.getByText("Manual.pdf")).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("sends a chat message and renders the streamed assistant reply", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.type(screen.getByRole("textbox"), "How do I calibrate?");
    await user.click(screen.getByRole("button", { name: /Send|发送/i }));

    expect(await screen.findByText("How do I calibrate?")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/Partial answer/)).toBeInTheDocument();
    });
    expect(streamChat).toHaveBeenCalledWith(
      "How do I calibrate?",
      null,
      ["doc-1"],
      expect.objectContaining({ onDelta: expect.any(Function), onDone: expect.any(Function) }),
    );
  });

  it("shows an error when chat streaming fails", async () => {
    streamChat.mockRejectedValue(new Error("Chat failed"));
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.type(screen.getByRole("textbox"), "Broken request");
    await user.click(screen.getByRole("button", { name: /Send|发送/i }));

    expect(await screen.findByText(/Chat failed/)).toBeInTheDocument();
    expect(screen.queryByText(/Partial answer/)).not.toBeInTheDocument();
  });

  it("opens the document viewer from an inline citation", async () => {
    streamChat.mockImplementation(async (_message, _sessionId, _docIds, handlers: StreamHandlers) => {
      handlers.onDone({
        sessionId: "session-1",
        content: "See [1] for the alarm reset steps.",
        citations: [
          {
            document_id: "doc-1",
            document_name: "Manual.pdf",
            page: 2,
            section: null,
            snippet: "Reset alarm E-204.",
            regions: [],
          },
        ],
        embeds: [],
        language: "en",
      });
    });

    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.type(screen.getByRole("textbox"), "Alarm help");
    await user.click(screen.getByRole("button", { name: /Send|发送/i }));

    const citationButton = await screen.findByRole("button", { name: "[1]" });
    await user.click(citationButton);

    expect(await screen.findByRole("button", { name: /Close document preview|关闭/i })).toBeInTheDocument();
    expect(document.querySelector(".doc-viewer-name")?.textContent).toBe("Manual.pdf");
  });

  it("orders right panels by open sequence when settings opens before the viewer", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Open settings|打开设置/i }));
    await screen.findByRole("dialog");
    await openCitationFromChat(user);

    expect(getRightPanelDomOrder()).toEqual(["settings", "viewer"]);
  });

  it("orders right panels by open sequence when the viewer opens before settings", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await openCitationFromChat(user);
    await user.click(screen.getByRole("button", { name: /Open settings|打开设置/i }));
    await screen.findByRole("dialog");

    expect(getRightPanelDomOrder()).toEqual(["viewer", "settings"]);
  });

  it("closes the document viewer when starting a new chat", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await openCitationFromChat(user);
    expect(document.querySelector(".doc-viewer-slot.is-open")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /New chat|新对话/i }));

    expect(document.querySelector(".doc-viewer-slot.is-closing")).toBeInTheDocument();
    await waitFor(() => {
      expect(document.querySelector(".doc-viewer-slot")).not.toBeInTheDocument();
    });
  });

  it("unmounts the viewer slot when closed", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await openCitationFromChat(user);
    expect(document.querySelector(".doc-viewer-slot.is-open")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Close document preview|关闭/i }));
    expect(document.querySelector(".doc-viewer-slot.is-closing")).toBeInTheDocument();
    await waitFor(() => {
      expect(document.querySelector(".doc-viewer-slot")).not.toBeInTheDocument();
    });
  });

  it("keeps the settings panel open when the viewer is closed", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Open settings|打开设置/i }));
    await screen.findByRole("dialog");
    await openCitationFromChat(user);

    await user.click(screen.getByRole("button", { name: /Close document preview|关闭/i }));

    expect(document.querySelector(".settings-panel.open")).toBeInTheDocument();
    await waitFor(() => {
      expect(document.querySelector(".doc-viewer-slot")).not.toBeInTheDocument();
    });
    expect(getRightPanelDomOrder()).toEqual(["settings"]);
  });

  it("does not reorder panels when updating an already open viewer", async () => {
    streamChat.mockImplementation(async (_message, _sessionId, _docIds, handlers: StreamHandlers) => {
      handlers.onDone({
        sessionId: "session-1",
        content: "See [1] and [2].",
        citations: [
          {
            document_id: "doc-1",
            document_name: "Manual.pdf",
            page: 1,
            section: null,
            snippet: "Page one.",
            regions: [],
          },
          {
            document_id: "doc-1",
            document_name: "Manual.pdf",
            page: 3,
            section: null,
            snippet: "Page three.",
            regions: [],
          },
        ],
        embeds: [],
        language: "en",
      });
    });

    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Open settings|打开设置/i }));
    await screen.findByRole("dialog");
    await user.type(screen.getByRole("textbox"), "Show pages");
    await user.click(screen.getByRole("button", { name: /Send|发送/i }));

    await user.click(await screen.findByRole("button", { name: "[1]" }));
    expect(getRightPanelDomOrder()).toEqual(["settings", "viewer"]);

    await user.click(screen.getByRole("button", { name: "[2]" }));
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: /Page number|页码/i })).toHaveValue("3");
    });
    expect(getRightPanelDomOrder()).toEqual(["settings", "viewer"]);
  });

  it("updates the viewer target when another citation is clicked while open", async () => {
    streamChat.mockImplementation(async (_message, _sessionId, _docIds, handlers: StreamHandlers) => {
      handlers.onDone({
        sessionId: "session-1",
        content: "See [1] and [2] for details.",
        citations: [
          {
            document_id: "doc-1",
            document_name: "Manual.pdf",
            page: 1,
            section: null,
            snippet: "Page one note.",
            regions: [],
          },
          {
            document_id: "doc-1",
            document_name: "Manual.pdf",
            page: 3,
            section: null,
            snippet: "Page three note.",
            regions: [],
          },
        ],
        embeds: [],
        language: "en",
      });
    });

    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.type(screen.getByRole("textbox"), "Show pages");
    await user.click(screen.getByRole("button", { name: /Send|发送/i }));

    await user.click(await screen.findByRole("button", { name: "[1]" }));
    expect(await screen.findByRole("textbox", { name: /Page number|页码/i })).toHaveValue("1");

    await user.click(screen.getByRole("button", { name: "[2]" }));
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: /Page number|页码/i })).toHaveValue("3");
    });
  });

  it("reindexes a document after confirmation", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getAllByRole("button", { name: /^Reindex$|^重新索引$/i })[0]!);

    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /^Reindex$|^重新索引$/i }));

    await waitFor(() => {
      expect(reindexDocument).toHaveBeenCalledWith("doc-1");
    });
  });

  it("shows an error when sending without selected documents", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("checkbox", { name: /Manual.pdf/i }));
    await user.type(screen.getByRole("textbox"), "Hello");
    await user.click(screen.getByRole("button", { name: /Send|发送/i }));

    expect(await screen.findByText(/Select at least one ready|请至少选择/i)).toBeInTheDocument();
    expect(streamChat).not.toHaveBeenCalled();
  });

  it("uploads a document from the sidebar file picker", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["pdf-bytes"], "Guide.pdf", { type: "application/pdf" });

    await user.upload(fileInput, file);

    await waitFor(() => {
      expect(uploadDocument).toHaveBeenCalled();
    });
    expect(listDocuments.mock.calls.length).toBeGreaterThan(1);
  });

  it("deletes a document after confirmation", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getAllByRole("button", { name: /Delete document|删除/i })[0]!);

    const dialog = await screen.findByRole("alertdialog");
    await user.click(
      within(dialog).getByRole("button", { name: /Delete document|删除/i }),
    );

    await waitFor(() => {
      expect(deleteDocument).toHaveBeenCalledWith("doc-1");
    });
  });

  it("handles a voice question over websocket", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Voice question|语音/i }));
    await user.click(screen.getByRole("button", { name: /Stop recording|停止/i }));

    await waitFor(() => {
      expect(activeVoiceSocket).not.toBeNull();
      expect(activeVoiceSocket?.send).toHaveBeenCalled();
    });

    activeVoiceSocket?.onmessage?.({
      data: JSON.stringify({ type: "transcript", text: "Voice question" }),
    } as MessageEvent);
    activeVoiceSocket?.onmessage?.({
      data: JSON.stringify({
        type: "done",
        session_id: "voice-session",
        content: "Voice answer",
        citations: [],
        embeds: [],
      }),
    } as MessageEvent);

    expect(await screen.findByText("Voice question")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/Voice answer/)).toBeInTheDocument();
    });
  });

  it("surfaces voice websocket connection errors", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Voice question|语音/i }));
    await user.click(screen.getByRole("button", { name: /Stop recording|停止/i }));

    await waitFor(() => expect(activeVoiceSocket).not.toBeNull());
    activeVoiceSocket?.onerror?.();

    expect(await screen.findByText(/Voice connection failed|语音连接失败/i)).toBeInTheDocument();
  });

  it("surfaces invalid voice websocket payloads", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Voice question|语音/i }));
    await user.click(screen.getByRole("button", { name: /Stop recording|停止/i }));

    await waitFor(() => expect(activeVoiceSocket).not.toBeNull());
    activeVoiceSocket?.onmessage?.({ data: "not-json" } as MessageEvent);

    expect(await screen.findByText(/Failed to parse voice|语音响应解析失败/i)).toBeInTheDocument();
  });

  it("shows an error when upload fails", async () => {
    uploadDocument.mockRejectedValue(new Error("Upload failed"));
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, new File(["pdf"], "Bad.pdf", { type: "application/pdf" }));

    expect(await screen.findByText(/Upload failed/)).toBeInTheDocument();
  });

  it("shows an error when reindex fails", async () => {
    reindexDocument.mockRejectedValue(new Error("Reindex failed"));
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getAllByRole("button", { name: /^Reindex$|^重新索引$/i })[0]!);
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /^Reindex$|^重新索引$/i }));

    expect(await screen.findByText(/Reindex failed/)).toBeInTheDocument();
  });

  it("does not delete a document when confirmation is cancelled", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getAllByRole("button", { name: /Delete document|删除/i })[0]!);
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /Cancel|取消/i }));

    expect(deleteDocument).not.toHaveBeenCalled();
  });

  it("switches locale from the header toggle", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: "中文" }));

    expect(screen.getByRole("button", { name: "中文" })).toHaveAttribute("aria-pressed", "true");
  });

  it("surfaces voice websocket disconnects", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Voice question|语音/i }));
    await user.click(screen.getByRole("button", { name: /Stop recording|停止/i }));

    await waitFor(() => expect(activeVoiceSocket).not.toBeNull());
    activeVoiceSocket?.onclose?.();

    expect(await screen.findByText(/Voice connection closed|语音连接已断开/i)).toBeInTheDocument();
  });

  it("surfaces voice stream error payloads", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Voice question|语音/i }));
    await user.click(screen.getByRole("button", { name: /Stop recording|停止/i }));

    await waitFor(() => expect(activeVoiceSocket).not.toBeNull());
    activeVoiceSocket?.onmessage?.({
      data: JSON.stringify({ type: "error", message: "Voice model failed" }),
    } as MessageEvent);

    expect(await screen.findByText(/Voice model failed/)).toBeInTheDocument();
  });

  it("shows an error when voice is sent without selected documents", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("checkbox", { name: /Manual.pdf/i }));
    await user.click(screen.getByRole("button", { name: /Voice question|语音/i }));
    await user.click(screen.getByRole("button", { name: /Stop recording|停止/i }));

    expect(await screen.findByText(/Select at least one ready|请至少选择/i)).toBeInTheDocument();
    expect(createVoiceSocket).not.toHaveBeenCalled();
  });

  it("surfaces microphone permission failures", async () => {
    vi.stubGlobal("navigator", {
      ...globalThis.navigator,
      language: "en-US",
      mediaDevices: {
        getUserMedia: vi.fn().mockRejectedValue(new Error("Mic denied")),
      },
    });

    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Voice question|语音/i }));

    expect(await screen.findByText(/Mic denied/)).toBeInTheDocument();
  });

  it("plays streamed voice response audio chunks", async () => {
    const play = vi.fn().mockResolvedValue(undefined);
    class MockAudio {
      onended: (() => void) | null = null;
      play = play;
      constructor(_src: string) {}
    }
    vi.stubGlobal("Audio", MockAudio);

    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Voice question|语音/i }));
    await user.click(screen.getByRole("button", { name: /Stop recording|停止/i }));

    await waitFor(() => expect(activeVoiceSocket).not.toBeNull());
    activeVoiceSocket?.onmessage?.({
      data: JSON.stringify({ type: "transcript", text: "Voice question" }),
    } as MessageEvent);
    activeVoiceSocket?.onmessage?.({
      data: JSON.stringify({ type: "audio", data: "YXNk" }),
    } as MessageEvent);

    await waitFor(() => {
      expect(play).toHaveBeenCalled();
    });
  });

  it("re-selects a document after it was unchecked", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    const checkbox = screen.getByRole("checkbox", { name: /Manual.pdf/i });
    await user.click(checkbox);
    expect(checkbox).not.toBeChecked();
    await user.click(checkbox);
    expect(checkbox).toBeChecked();
  });

  it("surfaces voice request timeout", async () => {
    let voiceTimeoutHandler: (() => void) | null = null;
    const originalSetTimeout = globalThis.setTimeout.bind(globalThis);
    const setTimeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation((handler, delay, ...args) => {
        if (delay === 300_000) {
          voiceTimeoutHandler = handler as () => void;
          return 999 as unknown as ReturnType<typeof setTimeout>;
        }
        return originalSetTimeout(handler, delay, ...args);
      });

    try {
      const user = userEvent.setup();
      renderApp();

      await screen.findByText("Manual.pdf");
      await user.click(screen.getByRole("button", { name: /Voice question|语音/i }));
      await user.click(screen.getByRole("button", { name: /Stop recording|停止/i }));

      await waitFor(() => expect(activeVoiceSocket).not.toBeNull());
      expect(voiceTimeoutHandler).not.toBeNull();
      voiceTimeoutHandler!();

      expect(
        await screen.findByText(/Voice request timed out|语音处理超时/i),
      ).toBeInTheDocument();
    } finally {
      setTimeoutSpy.mockRestore();
    }
  });

  it("starts with the sidebar closed on mobile", async () => {
    Object.defineProperty(window, "innerWidth", { value: 800, configurable: true });
    renderApp();

    await screen.findByText("Manual.pdf");
    expect(document.querySelector(".sidebar.open")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Open sidebar|打开侧边栏/i }),
    ).toBeInTheDocument();
  });

  it("closes the sidebar when the overlay is clicked on mobile", async () => {
    Object.defineProperty(window, "innerWidth", { value: 800, configurable: true });
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Open sidebar|打开侧边栏/i }));
    expect(document.querySelector(".sidebar.open")).toBeInTheDocument();

    await user.click(document.querySelector(".sidebar-overlay") as HTMLElement);

    expect(document.querySelector(".sidebar.open")).not.toBeInTheDocument();
  });

  it("closes the sidebar when the viewport switches to mobile", async () => {
    const mediaQueryListeners: Array<(event: MediaQueryListEvent) => void> = [];
    window.matchMedia = vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: (_event: string, listener: (event: MediaQueryListEvent) => void) => {
        mediaQueryListeners.push(listener);
      },
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })) as typeof window.matchMedia;

    Object.defineProperty(window, "innerWidth", { value: 1200, configurable: true });
    renderApp();

    await screen.findByText("Manual.pdf");
    expect(document.querySelector(".sidebar.open")).toBeInTheDocument();
    expect(mediaQueryListeners.length).toBeGreaterThan(0);

    await act(async () => {
      mediaQueryListeners[0]!({ matches: true } as MediaQueryListEvent);
    });

    expect(document.querySelector(".sidebar.open")).not.toBeInTheDocument();
  });

  it("polls documents while visible and pauses polling when hidden", async () => {
    listDocuments.mockResolvedValue([
      {
        ...sampleDocuments[0],
        status: "processing" as const,
        progress: 40,
        progress_message: "Indexing",
      },
    ]);

    renderApp();
    await waitFor(() => expect(listDocuments).toHaveBeenCalled());
    const initialCalls = listDocuments.mock.calls.length;

    vi.useFakeTimers();
    try {
      Object.defineProperty(document, "visibilityState", {
        value: "hidden",
        configurable: true,
      });
      document.dispatchEvent(new Event("visibilitychange"));

      await vi.advanceTimersByTimeAsync(2000);
      expect(listDocuments.mock.calls.length).toBe(initialCalls);

      Object.defineProperty(document, "visibilityState", {
        value: "visible",
        configurable: true,
      });
      document.dispatchEvent(new Event("visibilitychange"));

      await vi.advanceTimersByTimeAsync(500);
      expect(listDocuments.mock.calls.length).toBeGreaterThan(initialCalls);
    } finally {
      vi.useRealTimers();
      Object.defineProperty(document, "visibilityState", {
        value: "visible",
        configurable: true,
      });
    }
  });

  it("reopens the viewer when another citation is clicked during close", async () => {
    streamChat.mockImplementation(async (_message, _sessionId, _docIds, handlers: StreamHandlers) => {
      handlers.onDone({
        sessionId: "session-1",
        content: "See [1] and [2].",
        citations: [
          {
            document_id: "doc-1",
            document_name: "Manual.pdf",
            page: 1,
            section: null,
            snippet: "Page one.",
            regions: [],
          },
          {
            document_id: "doc-1",
            document_name: "Manual.pdf",
            page: 4,
            section: null,
            snippet: "Page four.",
            regions: [],
          },
        ],
        embeds: [],
        language: "en",
      });
    });

    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.type(screen.getByRole("textbox"), "Show pages");
    await user.click(screen.getByRole("button", { name: /Send|发送/i }));

    await user.click(await screen.findByRole("button", { name: "[1]" }));
    await user.click(
      await screen.findByRole("button", { name: /Close document preview|关闭/i }),
    );
    expect(document.querySelector(".doc-viewer-slot.is-open")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "[2]" }));

    await waitFor(() => {
      expect(document.querySelector(".doc-viewer-slot.is-open")).toBeInTheDocument();
    });
    expect(await screen.findByRole("textbox", { name: /Page number|页码/i })).toHaveValue("4");
  });

  it("continues voice playback when an audio chunk fails to play", async () => {
    let playCount = 0;
    const play = vi.fn().mockImplementation(() => {
      playCount += 1;
      if (playCount === 1) {
        return Promise.reject(new Error("play failed"));
      }
      return Promise.resolve();
    });
    class MockAudio {
      onended: (() => void) | null = null;
      play = play;
      constructor(_src: string) {}
    }
    vi.stubGlobal("Audio", MockAudio);

    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(screen.getByRole("button", { name: /Voice question|语音/i }));
    await user.click(screen.getByRole("button", { name: /Stop recording|停止/i }));

    await waitFor(() => expect(activeVoiceSocket).not.toBeNull());
    activeVoiceSocket?.onmessage?.({
      data: JSON.stringify({ type: "transcript", text: "Voice question" }),
    } as MessageEvent);
    activeVoiceSocket?.onmessage?.({
      data: JSON.stringify({ type: "audio", data: "YXNk" }),
    } as MessageEvent);
    activeVoiceSocket?.onmessage?.({
      data: JSON.stringify({ type: "audio", data: "Zmdo" }),
    } as MessageEvent);

    await waitFor(() => {
      expect(play.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });
});
