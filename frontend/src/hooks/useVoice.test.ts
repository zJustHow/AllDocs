/** @vitest-environment jsdom */
import { act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SetStateAction } from "react";
import { createVoiceSocket } from "../api";
import type { ChatMessage } from "../types";
import { renderHookWithI18n } from "./testUtils";
import { useVoice } from "./useVoice";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    createVoiceSocket: vi.fn(),
  };
});

let nextId = 0;
vi.mock("../utils/newId", () => ({
  newId: () => `voice-id-${++nextId}`,
}));

type MockWebSocket = {
  readyState: number;
  send: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  onopen: (() => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: (() => void) | null;
  onclose: (() => void) | null;
};

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

describe("useVoice", () => {
  const setError = vi.fn();
  const setScrollTargetId = vi.fn();
  const setSessionId = vi.fn();
  const setLoading = vi.fn();
  let messages: ChatMessage[] = [];
  const setMessages = vi.fn((updater: SetStateAction<ChatMessage[]>) => {
    messages = typeof updater === "function" ? updater(messages) : updater;
  });

  beforeEach(() => {
    nextId = 0;
    messages = [];
    setError.mockReset();
    setScrollTargetId.mockReset();
    setSessionId.mockReset();
    setLoading.mockReset();
    setMessages.mockClear();
    vi.mocked(createVoiceSocket).mockImplementation(createMockWebSocket);

    class MockFileReader {
      result: string | ArrayBuffer | null = null;
      error: DOMException | null = null;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;

      readAsDataURL() {
        this.result = "data:audio/webm;base64,YXVkaW8=";
        queueMicrotask(() => this.onload?.());
      }
    }

    vi.stubGlobal("FileReader", MockFileReader);

    vi.stubGlobal(
      "MediaRecorder",
      class {
        static isTypeSupported = vi.fn().mockReturnValue(true);
        mimeType = "audio/webm";
        state = "inactive";
        ondataavailable: ((event: { data: Blob }) => void) | null = null;
        onstop: (() => void) | null = null;

        constructor(
          _stream: unknown,
          options?: { mimeType?: string },
        ) {
          if (options?.mimeType) {
            this.mimeType = options.mimeType;
          }
        }

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

    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }],
        }),
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  function renderVoiceHook(selectedDocIds: string[] = ["doc-1"], loading = false) {
    return renderHookWithI18n(() =>
      useVoice({
        selectedDocIds,
        sessionId: "session-1",
        loading,
        isAdmin: true,
        readyDocCount: selectedDocIds.length,
        setMessages,
        setSessionId,
        setLoading,
        setScrollTargetId,
        setError,
      }),
    );
  }

  it("requires selected documents before sending voice input", async () => {
    const { result } = renderVoiceHook([]);

    await act(async () => {
      await result.current.startRecording();
    });
    expect(result.current.recording).toBe(true);

    await act(async () => {
      result.current.stopRecording();
    });

    await waitFor(() => {
      expect(setError).toHaveBeenCalled();
    });
    expect(createVoiceSocket).not.toHaveBeenCalled();
    expect(result.current.recording).toBe(false);
  });

  it("starts and stops recording, then opens a voice websocket", async () => {
    const { result } = renderVoiceHook();

    await act(async () => {
      await result.current.startRecording();
    });
    expect(result.current.recording).toBe(true);

    await act(async () => {
      result.current.stopRecording();
    });

    await waitFor(() => {
      expect(createVoiceSocket).toHaveBeenCalled();
    });

    const ws = vi.mocked(createVoiceSocket).mock.results[0]?.value as MockWebSocket;
    expect(ws.send).toHaveBeenCalledWith(
      JSON.stringify({
        type: "audio",
        data: "YXVkaW8=",
        mime_type: "audio/webm;codecs=opus",
        language: "en",
        session_id: "session-1",
        doc_ids: ["doc-1"],
        with_audio: true,
      }),
    );
    expect(result.current.recording).toBe(false);
  });

  it("adds transcript messages when the websocket emits a transcript event", async () => {
    const { result } = renderVoiceHook();

    await act(async () => {
      await result.current.startRecording();
    });
    await act(async () => {
      result.current.stopRecording();
    });

    await waitFor(() => {
      expect(createVoiceSocket).toHaveBeenCalled();
    });

    const ws = vi.mocked(createVoiceSocket).mock.results[0]?.value as MockWebSocket;

    await act(async () => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "transcript", text: "What is on page 2?" }),
      } as MessageEvent);
    });

    expect(setScrollTargetId).toHaveBeenCalledWith("voice-id-2");
    expect(messages).toEqual([
      {
        id: "voice-id-2",
        role: "user",
        content: "What is on page 2?",
      },
      {
        id: "voice-id-1",
        role: "assistant",
        content: "",
        streaming: true,
        citations: [],
        agentSteps: [],
        agentRunning: true,
      },
    ]);
  });

  it("reports websocket parse failures", async () => {
    const { result } = renderVoiceHook();

    await act(async () => {
      await result.current.startRecording();
    });
    await act(async () => {
      result.current.stopRecording();
    });

    await waitFor(() => {
      expect(createVoiceSocket).toHaveBeenCalled();
    });

    const ws = vi.mocked(createVoiceSocket).mock.results[0]?.value as MockWebSocket;

    await act(async () => {
      ws.onmessage?.({ data: "not-json" } as MessageEvent);
    });

    expect(setError).toHaveBeenCalled();
    expect(setLoading).toHaveBeenCalledWith(false);
  });

  it("does not request microphone access while another response is loading", async () => {
    const getUserMedia = vi.mocked(navigator.mediaDevices.getUserMedia);
    const { result } = renderVoiceHook(["doc-1"], true);

    await act(async () => {
      await result.current.startRecording();
    });

    expect(getUserMedia).not.toHaveBeenCalled();
    expect(result.current.recording).toBe(false);
  });

  it("reports microphone permission failures", async () => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(
      new Error("microphone denied"),
    );
    const { result } = renderVoiceHook();

    await act(async () => {
      await result.current.startRecording();
    });

    expect(setError).toHaveBeenCalledWith("Error: microphone denied");
    expect(result.current.recording).toBe(false);
    expect(createVoiceSocket).not.toHaveBeenCalled();
  });

  it("finishes with an error when the voice socket disconnects early", async () => {
    const { result } = renderVoiceHook();

    await act(async () => {
      await result.current.startRecording();
    });
    await act(async () => {
      result.current.stopRecording();
    });
    await waitFor(() => {
      expect(createVoiceSocket).toHaveBeenCalled();
    });

    const ws = vi.mocked(createVoiceSocket).mock.results[0]?.value as MockWebSocket;
    await act(async () => {
      ws.onclose?.();
    });

    expect(setError).toHaveBeenCalled();
    expect(setLoading).toHaveBeenLastCalledWith(false);
    expect(result.current.voiceStatus).toBeNull();
  });
});
