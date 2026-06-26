import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { streamChat } from "../api";
import { createAssistantStreamController } from "../chatStream";
import { useI18n } from "../i18n";
import type { ChatMessage } from "../types";
import { newId } from "../utils/newId";

interface UseChatOptions {
  selectedDocIds: string[];
  setScrollTargetId: (id: string | null) => void;
  setError: Dispatch<SetStateAction<string | null>>;
  isAdmin: boolean;
  readyDocCount: number;
}

export function useChat({
  selectedDocIds,
  setScrollTargetId,
  setError,
  isAdmin,
  readyDocCount,
}: UseChatOptions) {
  const { t } = useI18n();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }, [input]);

  const clearChat = useCallback(
    (onReset?: () => void) => {
      setMessages([]);
      setSessionId(null);
      setError(null);
      setInput("");
      setScrollTargetId(null);
      onReset?.();
    },
    [setError, setScrollTargetId],
  );

  const sendText = useCallback(
    async (textOverride?: string) => {
      const text = (textOverride ?? input).trim();
      if (!text || loading) return;
      if (readyDocCount === 0) {
        setError(t(isAdmin ? "chat.selectDocError" : "chat.noDocsError"));
        return;
      }

      setError(null);
      setInput("");
      setLoading(true);

      let assistantId: string | null = null;
      let stream: ReturnType<typeof createAssistantStreamController> | null =
        null;
      try {
        const userMessage: ChatMessage = {
          id: newId(),
          role: "user",
          content: text,
        };
        setScrollTargetId(userMessage.id);
        assistantId = newId();
        setMessages((prev) => [
          ...prev,
          userMessage,
          {
            id: assistantId!,
            role: "assistant",
            content: "",
            streaming: true,
            agentSteps: [],
            agentRunning: true,
          },
        ]);

        stream = createAssistantStreamController({
          assistantId: assistantId!,
          setMessages,
          setSessionId,
          setError,
          setLoading,
        });

        await streamChat(text, sessionId, selectedDocIds, stream.handlers);
      } catch (err) {
        stream?.flush();
        setError(String(err));
        if (assistantId) {
          setMessages((prev) => prev.filter((msg) => msg.id !== assistantId));
        }
      } finally {
        setLoading(false);
      }
    },
    [input, loading, selectedDocIds, sessionId, setError, setScrollTargetId, t, isAdmin, readyDocCount],
  );

  return {
    messages,
    setMessages,
    input,
    setInput,
    sessionId,
    setSessionId,
    loading,
    setLoading,
    textareaRef,
    clearChat,
    sendText,
  };
}
