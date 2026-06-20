/** @vitest-environment jsdom */
import { act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { streamChat } from "../api";
import { renderHookWithI18n } from "./testUtils";
import { useChat } from "./useChat";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    streamChat: vi.fn(),
  };
});

let nextId = 0;
vi.mock("../utils/newId", () => ({
  newId: () => `generated-id-${++nextId}`,
}));

describe("useChat", () => {
  const setError = vi.fn();
  const setScrollTargetId = vi.fn();

  beforeEach(() => {
    nextId = 0;
    setError.mockReset();
    setScrollTargetId.mockReset();
    vi.mocked(streamChat).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  function renderChatHook(selectedDocIds: string[] = ["doc-1"]) {
    return renderHookWithI18n(() =>
      useChat({ selectedDocIds, setScrollTargetId, setError }),
    );
  }

  it("clears chat state and runs an optional reset callback", () => {
    const onReset = vi.fn();
    const { result } = renderChatHook();

    act(() => {
      result.current.setInput("hello");
      result.current.setSessionId("session-1");
      result.current.setMessages([
        { id: "m1", role: "user", content: "hello" },
      ]);
    });

    act(() => {
      result.current.clearChat(onReset);
    });

    expect(result.current.messages).toEqual([]);
    expect(result.current.sessionId).toBeNull();
    expect(result.current.input).toBe("");
    expect(setError).toHaveBeenCalledWith(null);
    expect(setScrollTargetId).toHaveBeenCalledWith(null);
    expect(onReset).toHaveBeenCalled();
  });

  it("requires selected documents before sending", async () => {
    const { result } = renderChatHook([]);

    act(() => {
      result.current.setInput("Hello");
    });

    await act(async () => {
      await result.current.sendText();
    });

    expect(setError).toHaveBeenCalled();
    expect(streamChat).not.toHaveBeenCalled();
    expect(result.current.messages).toEqual([]);
  });

  it("appends user and assistant messages then streams a reply", async () => {
    const { result } = renderChatHook();

    act(() => {
      result.current.setInput("Summarize the manual");
    });

    await act(async () => {
      await result.current.sendText();
    });

    expect(setScrollTargetId).toHaveBeenCalledWith("generated-id-1");
    expect(result.current.messages).toEqual([
      {
        id: "generated-id-1",
        role: "user",
        content: "Summarize the manual",
      },
      {
        id: "generated-id-2",
        role: "assistant",
        content: "",
        streaming: true,
        agentSteps: [],
        agentRunning: true,
      },
    ]);
    expect(streamChat).toHaveBeenCalledWith(
      "Summarize the manual",
      null,
      ["doc-1"],
      expect.objectContaining({
        onDelta: expect.any(Function),
        onDone: expect.any(Function),
      }),
    );
    expect(result.current.input).toBe("");
    expect(result.current.loading).toBe(false);
  });

  it("removes the assistant placeholder when streaming fails", async () => {
    vi.mocked(streamChat).mockRejectedValueOnce(new Error("stream failed"));
    const { result } = renderChatHook();

    act(() => {
      result.current.setInput("Hello");
    });

    await act(async () => {
      await result.current.sendText();
    });

    await waitFor(() => {
      expect(result.current.messages).toEqual([
        {
          id: "generated-id-1",
          role: "user",
          content: "Hello",
        },
      ]);
    });
    expect(setError).toHaveBeenLastCalledWith("Error: stream failed");
  });
});
