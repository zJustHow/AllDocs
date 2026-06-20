import { describe, expect, it, vi } from "vitest";
import {
  createVoiceSocket,
  deleteDocument,
  documentFileUrl,
  documentPageRenderUrl,
  fetchSettings,
  listDocuments,
  patchSettings,
  streamChat,
} from "./api";

function mockSseResponse(events: Array<Record<string, unknown>>) {
  const body = events.map((event) => `data: ${JSON.stringify(event)}\n`).join("");
  return {
    ok: true,
    body: new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(body));
        controller.close();
      },
    }),
  };
}

describe("document URL builders", () => {
  it("builds file and page render URLs", () => {
    expect(documentFileUrl("doc-1")).toBe("/api/v1/documents/doc-1/file");
    expect(documentPageRenderUrl("doc-1", 3)).toBe(
      "/api/v1/documents/doc-1/pages/3/render?scale=2",
    );
    expect(documentPageRenderUrl("doc-1", 5, 3)).toBe(
      "/api/v1/documents/doc-1/pages/5/render?scale=3",
    );
  });
});

describe("listDocuments", () => {
  it("returns parsed JSON on success", async () => {
    const docs = [{ id: "1", name: "Manual", status: "ready" }];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => docs,
      }),
    );

    await expect(listDocuments()).resolves.toEqual(docs);
    vi.unstubAllGlobals();
  });

  it("throws when response is not ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
      }),
    );

    await expect(listDocuments()).rejects.toThrow();
    vi.unstubAllGlobals();
  });
});

describe("deleteDocument", () => {
  it("throws when delete fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
      }),
    );

    await expect(deleteDocument("doc-1")).rejects.toThrow();
    vi.unstubAllGlobals();
  });
});

describe("streamChat", () => {
  it("dispatches SSE payloads to handlers", async () => {
    const onDelta = vi.fn();
    const onDone = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockSseResponse([
          { type: "status", stage: "thinking" },
          { type: "delta", content: "Hi" },
          {
            type: "done",
            session_id: "s1",
            content: "Hi there",
            citations: [],
            embeds: [],
            language: "zh",
          },
        ]),
      ),
    );

    await streamChat("hello", null, [], {
      onDelta,
      onDone,
      onError: vi.fn(),
    });

    expect(onDelta).toHaveBeenCalledWith("Hi");
    expect(onDone).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "s1",
        content: "Hi there",
      }),
    );
    vi.unstubAllGlobals();
  });

  it("reports incomplete streams when done event is missing", async () => {
    const onError = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockSseResponse([{ type: "delta", content: "partial" }]),
      ),
    );

    await streamChat("hello", null, [], {
      onDelta: vi.fn(),
      onDone: vi.fn(),
      onError,
    });

    expect(onError).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

describe("settings API", () => {
  it("loads and patches settings", async () => {
    const payload = { groups: [{ id: "llm", fields: [] }] };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => payload })
      .mockResolvedValueOnce({ ok: true, json: async () => payload });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchSettings()).resolves.toEqual(payload);
    await expect(patchSettings({ LLM_MODEL: "gpt-4" })).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    vi.unstubAllGlobals();
  });
});

describe("createVoiceSocket", () => {
  it("opens a websocket on the voice endpoint", () => {
    const sockets: Array<{ url: string }> = [];
    class MockWebSocket {
      url: string;
      constructor(url: string) {
        this.url = url;
        sockets.push(this);
      }
    }

    vi.stubGlobal("window", { location: { protocol: "https:", host: "app.example.com" } });
    vi.stubGlobal("WebSocket", MockWebSocket);

    createVoiceSocket();

    expect(sockets[0]?.url).toBe("wss://app.example.com/ws/voice");
    vi.unstubAllGlobals();
  });
});
