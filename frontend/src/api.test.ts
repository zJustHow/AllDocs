/** @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import {
  createVoiceSocket,
  deleteDocument,
  documentFileUrl,
  documentPageRenderUrl,
  fetchSettings,
  listDocuments,
  patchSettings,
  reindexDocument,
  streamChat,
  uploadDocument,
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

  it("forwards stream error events to handlers", async () => {
    const onError = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockSseResponse([
          { type: "error", message: "model unavailable" },
        ]),
      ),
    );

    await streamChat("hello", null, [], {
      onDelta: vi.fn(),
      onDone: vi.fn(),
      onError,
    });

    expect(onError).toHaveBeenCalledWith("model unavailable");
    vi.unstubAllGlobals();
  });

  it("forwards agent and status events when handlers are provided", async () => {
    const onStatus = vi.fn();
    const onAgentStep = vi.fn();
    const onAgentThoughtDelta = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockSseResponse([
          { type: "status", stage: "thinking" },
          {
            type: "agent_step_start",
            step: 1,
            thought: "Searching",
            action: "search_chunks",
          },
          {
            type: "agent_thought_delta",
            step: 1,
            field: "content",
            delta: " more",
          },
        ]),
      ),
    );

    await streamChat("hello", null, [], {
      onStatus,
      onAgentStep,
      onAgentThoughtDelta,
      onDelta: vi.fn(),
      onDone: vi.fn(),
      onError: vi.fn(),
    });

    expect(onStatus).toHaveBeenCalledWith("thinking");
    expect(onAgentStep).toHaveBeenCalledWith(
      expect.objectContaining({ step: 1, status: "running" }),
    );
    expect(onAgentThoughtDelta).toHaveBeenCalledWith({
      step: 1,
      field: "content",
      delta: " more",
    });
    vi.unstubAllGlobals();
  });

  it("forwards citations and embeds events to handlers", async () => {
    const onCitations = vi.fn();
    const onEmbeds = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockSseResponse([
          { type: "citations", citations: [{ document_id: "d1" }] },
          { type: "embeds", embeds: [{ ref: 1, document_id: "d1", page: 1, url: "/x.png" }] },
          {
            type: "done",
            session_id: "s1",
            citations: [],
            embeds: [],
            language: "en",
          },
        ]),
      ),
    );

    await streamChat("hello", null, [], {
      onCitations,
      onEmbeds,
      onDelta: vi.fn(),
      onDone: vi.fn(),
      onError: vi.fn(),
    });

    expect(onCitations).toHaveBeenCalled();
    expect(onEmbeds).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("skips malformed SSE JSON lines", async () => {
    const onDelta = vi.fn();
    const onDone = vi.fn();
    const body = "data: not-json\n" +
      `data: ${JSON.stringify({ type: "delta", content: "Hi" })}\n` +
      `data: ${JSON.stringify({
        type: "done",
        session_id: "s1",
        citations: [],
        embeds: [],
        language: "en",
      })}\n`;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        body: new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode(body));
            controller.close();
          },
        }),
      }),
    );

    await streamChat("hello", null, [], {
      onDelta,
      onDone,
      onError: vi.fn(),
    });

    expect(onDelta).toHaveBeenCalledWith("Hi");
    expect(onDone).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("throws when chat request fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
      }),
    );

    await expect(
      streamChat("hello", null, [], {
        onDelta: vi.fn(),
        onDone: vi.fn(),
        onError: vi.fn(),
      }),
    ).rejects.toThrow();
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
    await expect(patchSettings({ llm_model: "gpt-4" })).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    vi.unstubAllGlobals();
  });

  it("throws when fetch settings fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
      }),
    );

    await expect(fetchSettings()).rejects.toThrow();
    vi.unstubAllGlobals();
  });

  it("throws when patch settings fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        text: async () => "validation failed",
      }),
    );

    await expect(patchSettings({ llm_model: "bad" })).rejects.toThrow("validation failed");
    vi.unstubAllGlobals();
  });
});

describe("uploadDocument", () => {
  it("uploads multipart form data", async () => {
    const doc = { id: "doc-2", name: "Guide.pdf", status: "ready" };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => doc,
      }),
    );

    const file = new File(["bytes"], "Guide.pdf", { type: "application/pdf" });
    await expect(uploadDocument(file)).resolves.toEqual(doc);
    vi.unstubAllGlobals();
  });

  it("throws the fallback upload error when response body is empty", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        text: async () => "",
      }),
    );

    const file = new File(["bytes"], "Guide.pdf", { type: "application/pdf" });
    await expect(uploadDocument(file)).rejects.toThrow(/Upload failed|上传失败/i);
    vi.unstubAllGlobals();
  });
});

describe("reindexDocument", () => {
  it("throws when reindex fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        text: async () => "reindex failed",
      }),
    );

    await expect(reindexDocument("doc-1")).rejects.toThrow("reindex failed");
    vi.unstubAllGlobals();
  });

  it("returns parsed JSON on success", async () => {
    const doc = { id: "doc-1", name: "Manual.pdf", status: "ready" };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => doc,
      }),
    );

    await expect(reindexDocument("doc-1")).resolves.toEqual(doc);
    vi.unstubAllGlobals();
  });

  it("throws the fallback reindex error when response body is empty", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        text: async () => "",
      }),
    );

    await expect(reindexDocument("doc-1")).rejects.toThrow(/Reindex failed|重新索引失败/i);
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
