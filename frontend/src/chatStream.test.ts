import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SetStateAction } from "react";
import { createAssistantStreamController } from "./chatStream";
import { getStreamingContent } from "./streamingContent";
import type { ChatMessage } from "./types";

function makeAssistantMessage(id = "assistant-1"): ChatMessage {
  return {
    id,
    role: "assistant",
    content: "",
    streaming: true,
    agentRunning: true,
    agentSteps: [],
  };
}

function createController(initialMessages: ChatMessage[] = [makeAssistantMessage()]) {
  let messages = initialMessages;
  const setMessages = vi.fn((updater: SetStateAction<ChatMessage[]>) => {
    messages = typeof updater === "function" ? updater(messages) : updater;
  });
  const setSessionId = vi.fn();
  const setError = vi.fn();
  const setLoading = vi.fn();
  const onAudio = vi.fn();

  const controller = createAssistantStreamController({
    assistantId: "assistant-1",
    setMessages,
    setSessionId,
    setError,
    setLoading,
    onAudio,
  });

  return {
    controller,
    get messages() {
      return messages;
    },
    setMessages,
    setSessionId,
    setError,
    setLoading,
    onAudio,
  };
}

describe("createAssistantStreamController", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("buffers delta text in the streaming store", () => {
    const ctx = createController();

    ctx.controller.handlers.onDelta("Hello");
    vi.runAllTimers();

    expect(ctx.messages[0]?.agentRunning).toBe(false);
    expect(getStreamingContent("assistant-1")).toBe("Hello");
  });

  it("merges agent steps and thought deltas", () => {
    const ctx = createController();

    ctx.controller.dispatchPayload({
      type: "agent_step_start",
      step: 1,
      thought: "Planning",
      action: "plan",
    });
    ctx.controller.dispatchPayload({
      type: "agent_thought_delta",
      step: 1,
      field: "content",
      delta: " more",
    });
    vi.runAllTimers();

    expect(ctx.messages[0]?.agentSteps).toEqual([
      expect.objectContaining({
        step: 1,
        thought: "Planning more",
        status: "running",
      }),
    ]);
  });

  it("finalizes assistant message on done payload", () => {
    const ctx = createController();

    ctx.controller.handlers.onDelta("Partial");
    vi.runAllTimers();
    ctx.controller.dispatchPayload({
      type: "done",
      session_id: "session-42",
      content: "Final answer",
      citations: [],
      embeds: [],
    });

    expect(ctx.setSessionId).toHaveBeenCalledWith("session-42");
    expect(ctx.setLoading).toHaveBeenCalledWith(false);
    expect(ctx.messages[0]).toMatchObject({
      streaming: false,
      agentRunning: false,
      content: "Final answer",
    });
  });

  it("handles error payloads by surfacing streamed content", () => {
    const ctx = createController();

    ctx.controller.handlers.onDelta("Oops");
    vi.runAllTimers();
    ctx.controller.handlers.onError("stream failed");

    expect(ctx.setError).toHaveBeenCalledWith("stream failed");
    expect(ctx.messages[0]).toMatchObject({
      streaming: false,
      content: "Oops",
    });
  });

  it("forwards audio payloads to optional callback", () => {
    const ctx = createController();

    expect(
      ctx.controller.dispatchPayload({
        type: "audio",
        data: "base64-chunk",
      }),
    ).toBe("continue");
    expect(ctx.onAudio).toHaveBeenCalledWith("base64-chunk");
  });

  it("accepts answer_delta payloads", () => {
    const ctx = createController();

    ctx.controller.dispatchPayload({ type: "answer_delta", content: "Delta" });
    vi.runAllTimers();

    expect(getStreamingContent("assistant-1")).toBe("Delta");
  });

  it("patches citations and embeds on intermediate events", () => {
    const ctx = createController();
    const citation = {
      document_id: "doc-1",
      document_name: "Manual",
      page: 1,
      section: null,
      snippet: "note",
      regions: [],
    };
    const embed = {
      ref: 1,
      document_id: "doc-1",
      page: 1,
      type: "figure",
      url: "/x.png",
      regions: [],
    };

    ctx.controller.handlers.onCitations([citation]);
    ctx.controller.handlers.onEmbeds([embed]);

    expect(ctx.messages[0]?.citations).toEqual([citation]);
    expect(ctx.messages[0]?.embeds).toEqual([embed]);
  });

  it("handles dispatch error payload and clears streaming buffer", () => {
    const ctx = createController();

    ctx.controller.handlers.onDelta("Partial");
    vi.runAllTimers();

    expect(ctx.controller.dispatchPayload({ type: "error", message: "boom" })).toBe("error");
    expect(ctx.messages[0]).toMatchObject({
      streaming: false,
      agentRunning: false,
      content: "Partial",
    });
    expect(getStreamingContent("assistant-1")).toBe("");
  });
});
