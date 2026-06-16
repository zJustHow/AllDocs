import type { Dispatch, SetStateAction } from "react";
import { upsertAgentStep } from "./agentStepUtils";
import { createDeltaBatcher } from "./streamBatch";
import type { AgentStepEvent, ChatMessage, Citation, MessageEmbed } from "./types";

export type StreamDispatchResult = "continue" | "done" | "error";

export interface AssistantStreamControllerOptions {
  assistantId: string;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setSessionId: (sessionId: string) => void;
  setError: (message: string) => void;
  setLoading: (loading: boolean) => void;
  onAudio?: (base64: string) => void;
}

export interface AssistantStreamController {
  deltaBatcher: ReturnType<typeof createDeltaBatcher>;
  flush: () => void;
  handlers: {
    onAgentStep: (step: AgentStepEvent) => void;
    onCitations: (citations: Citation[]) => void;
    onEmbeds: (embeds: MessageEmbed[]) => void;
    onDelta: (delta: string) => void;
    onDone: (payload: {
      sessionId: string;
      content?: string;
      citations: Citation[];
      embeds: MessageEmbed[];
    }) => void;
    onError: (message: string) => void;
  };
  dispatchPayload: (payload: {
    type: string;
    [key: string]: unknown;
  }) => StreamDispatchResult;
}

export function createAssistantStreamController(
  options: AssistantStreamControllerOptions,
): AssistantStreamController {
  const {
    assistantId,
    setMessages,
    setSessionId,
    setError,
    setLoading,
    onAudio,
  } = options;

  const patchAssistant = (patch: Partial<ChatMessage>) => {
    setMessages((prev) =>
      prev.map((msg) => (msg.id === assistantId ? { ...msg, ...patch } : msg)),
    );
  };

  const deltaBatcher = createDeltaBatcher((delta) => {
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === assistantId
          ? { ...msg, content: msg.content + delta, agentRunning: false }
          : msg,
      ),
    );
  });

  const finalizeAssistant = (payload: {
    content?: string;
    citations?: ChatMessage["citations"];
    embeds?: ChatMessage["embeds"];
  }) => {
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === assistantId
          ? {
              ...msg,
              streaming: false,
              agentRunning: false,
              content: payload.content ?? msg.content,
              citations: payload.citations ?? msg.citations,
              embeds: payload.embeds ?? msg.embeds,
            }
          : msg,
      ),
    );
  };

  const handlers = {
    onAgentStep: (step: AgentStepEvent) => {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantId
            ? { ...msg, agentSteps: upsertAgentStep(msg.agentSteps ?? [], step) }
            : msg,
        ),
      );
    },
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
      deltaBatcher.flush();
      setSessionId(sessionId);
      setLoading(false);
      finalizeAssistant({ content, citations, embeds });
    },
    onError: (message: string) => {
      deltaBatcher.flush();
      setError(message);
      setLoading(false);
      patchAssistant({ streaming: false, agentRunning: false });
    },
  };

  const dispatchPayload = (payload: {
    type: string;
    [key: string]: unknown;
  }): StreamDispatchResult => {
    if (payload.type === "agent_step" || payload.type === "agent_step_start") {
      handlers.onAgentStep({
        step: payload.step as number,
        thought: (payload.thought as string) ?? "",
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
      deltaBatcher.flush();
      setSessionId(payload.session_id as string);
      setLoading(false);
      finalizeAssistant({
        content: payload.content as string | undefined,
        citations: (payload.citations as ChatMessage["citations"]) ?? [],
        embeds: (payload.embeds as ChatMessage["embeds"]) ?? [],
      });
      return "done";
    }

    if (payload.type === "error") {
      deltaBatcher.flush();
      patchAssistant({ streaming: false, agentRunning: false });
      return "error";
    }

    return "continue";
  };

  return {
    deltaBatcher,
    flush: () => deltaBatcher.flush(),
    handlers,
    dispatchPayload,
  };
}
