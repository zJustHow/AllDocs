/** @vitest-environment jsdom */
import { render, screen, waitFor, within } from "@testing-library/react";
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

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
        state = "inactive";
        ondataavailable: ((event: { data: Blob }) => void) | null = null;
        onstop: (() => void) | null = null;

        constructor(_stream: MediaStream) {}

        start() {
          this.state = "recording";
        }

        requestData() {
          this.ondataavailable?.({
            data: new Blob(["audio-bytes"], { type: "audio/webm" }),
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

  it("sends a suggestion chip from the welcome screen", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByText("Manual.pdf");
    await user.click(
      screen.getByRole("button", { name: /How do I handle alarm E-204|如何处理 E-204/i }),
    );

    expect(await screen.findByText(/How do I handle alarm E-204|如何处理 E-204/i)).toBeInTheDocument();
    expect(streamChat).toHaveBeenCalledWith(
      "How do I handle alarm E-204?",
      null,
      ["doc-1"],
      expect.any(Object),
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
});
