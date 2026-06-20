import type { Dispatch, SetStateAction } from "react";
import { flushSync } from "react-dom";
import {
  appendAgentSteps,
  appendAgentThoughtDeltas,
  clearAgentSteps,
  getAgentSteps,
  initAgentSteps,
  setAgentRunning,
} from "./agentStepsStore";
import { createDeltaBatcher, createEventBatcher } from "./streamBatch";
import {
  appendStreamingContent,
  clearStreamingContent,
  getStreamingContent,
  initStreamingContent,
} from "./streamingContent";
import type {
  AgentStepEvent,
  AgentThoughtDelta,
  ChatMessage,
  Citation,
  MessageEmbed,
} from "./types";

type StreamDispatchResult = "continue" | "done" | "error";

interface AssistantStreamControllerOptions {
  assistantId: string;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setSessionId: (sessionId: string) => void;
  setError: (message: string) => void;
  setLoading: (loading: boolean) => void;
  onAudio?: (base64: string) => void;
}

export function createAssistantStreamController(
  options: AssistantStreamControllerOptions,
) {
  const {
    assistantId,
    setMessages,
    setSessionId,
    setError,
    setLoading,
    onAudio,
  } = options;

  initStreamingContent(assistantId);
  initAgentSteps(assistantId);
  let contentStarted = false;

  const patchAssistant = (patch: Partial<ChatMessage>) => {
    setMessages((prev) =>
      prev.map((msg) => (msg.id === assistantId ? { ...msg, ...patch } : msg)),
    );
  };

  const deltaBatcher = createDeltaBatcher((delta) => {
    appendStreamingContent(assistantId, delta);
    if (!contentStarted) {
      contentStarted = true;
      setAgentRunning(assistantId, false);
      patchAssistant({ agentRunning: false });
    }
  });

  const agentStepBatcher = createEventBatcher<AgentStepEvent>((steps) => {
    appendAgentSteps(assistantId, steps);
  });

  const agentThoughtDeltaBatcher = createEventBatcher<AgentThoughtDelta>((deltas) => {
    appendAgentThoughtDeltas(assistantId, deltas);
  });

  const finalizeAssistant = (payload: {
    content?: string;
    citations?: ChatMessage["citations"];
    embeds?: ChatMessage["embeds"];
  }) => {
    const streamed = getStreamingContent(assistantId);
    const agentSteps = getAgentSteps(assistantId);
    flushSync(() => {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantId
            ? {
                ...msg,
                streaming: false,
                agentRunning: false,
                content: payload.content ?? (streamed || msg.content),
                citations: payload.citations ?? msg.citations,
                embeds: payload.embeds ?? msg.embeds,
                agentSteps,
              }
            : msg,
        ),
      );
    });
    clearAgentSteps(assistantId);
    clearStreamingContent(assistantId);
  };

  const flushAll = () => {
    deltaBatcher.flush();
    agentStepBatcher.flush();
    agentThoughtDeltaBatcher.flush();
  };

  const handleDone = (
    sessionId: string,
    payload: {
      content?: string;
      citations?: ChatMessage["citations"];
      embeds?: ChatMessage["embeds"];
    },
  ) => {
    flushAll();
    setSessionId(sessionId);
    setLoading(false);
    finalizeAssistant(payload);
  };

  const handleStreamError = (message?: string) => {
    flushAll();
    const streamed = getStreamingContent(assistantId);
    const agentSteps = getAgentSteps(assistantId);
    if (message) {
      setError(message);
      setLoading(false);
    }
    flushSync(() => {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantId
            ? {
                ...msg,
                streaming: false,
                agentRunning: false,
                content: streamed,
                agentSteps,
              }
            : msg,
        ),
      );
    });
    clearAgentSteps(assistantId);
    clearStreamingContent(assistantId);
  };

  const handlers = {
    onAgentStep: (step: AgentStepEvent) => agentStepBatcher.push(step),
    onAgentThoughtDelta: (delta: AgentThoughtDelta) =>
      agentThoughtDeltaBatcher.push(delta),
    onCitations: (citations: Citation[]) => patchAssistant({ citations }),
    onEmbeds: (embeds: MessageEmbed[]) => patchAssistant({ embeds }),
    onDelta: (delta: string) => deltaBatcher.push(delta),
    onDone: ({
      sessionId,
      content,
      citations,
      embeds,
    }: {
      sessionId: string;
      content?: string;
      citations: Citation[];
      embeds: MessageEmbed[];
    }) => {
      handleDone(sessionId, { content, citations, embeds });
    },
    onError: (message: string) => {
      handleStreamError(message);
    },
  };

  const dispatchPayload = (payload: {
    type: string;
    [key: string]: unknown;
  }): StreamDispatchResult => {
    if (payload.type === "agent_thought_delta") {
      handlers.onAgentThoughtDelta({
        step: payload.step as number,
        field: (payload.field as AgentThoughtDelta["field"]) ?? "content",
        delta: (payload.delta as string) ?? "",
      });
      return "continue";
    }

    if (payload.type === "agent_step" || payload.type === "agent_step_start") {
      handlers.onAgentStep({
        step: payload.step as number,
        thought: (payload.thought as string) ?? "",
        reasoning: (payload.reasoning as string) ?? "",
        action: (payload.action as string) ?? "",
        action_input: (payload.action_input as Record<string, unknown>) ?? {},
        observation: (payload.observation as string) ?? "",
        evidence_count: payload.evidence_count as number | undefined,
        status: payload.type === "agent_step_start" ? "running" : "done",
      });
      return "continue";
    }

    if (payload.type === "citations") {
      handlers.onCitations((payload.citations as Citation[]) ?? []);
      return "continue";
    }

    if (payload.type === "embeds") {
      handlers.onEmbeds((payload.embeds as MessageEmbed[]) ?? []);
      return "continue";
    }

    if (payload.type === "delta" || payload.type === "answer_delta") {
      deltaBatcher.push(payload.content as string);
      return "continue";
    }

    if (payload.type === "audio") {
      onAudio?.(payload.data as string);
      return "continue";
    }

    if (payload.type === "done") {
      handleDone(payload.session_id as string, {
        content: payload.content as string | undefined,
        citations: (payload.citations as ChatMessage["citations"]) ?? [],
        embeds: (payload.embeds as ChatMessage["embeds"]) ?? [],
      });
      return "done";
    }

    if (payload.type === "error") {
      handleStreamError();
      return "error";
    }

    return "continue";
  };

  return {
    flush: flushAll,
    handlers,
    dispatchPayload,
  };
}
