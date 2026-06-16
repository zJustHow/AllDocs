import { memo, useCallback, type RefCallback } from "react";
import AgentSteps from "./AgentSteps";
import { useI18n } from "./i18n";
import { AllDocsIcon } from "./icons";
import MessageContent from "./MessageContent";
import { useStreamingContent } from "./streamingContent";
import type { ChatMessage } from "./types";
import type { ViewerTarget } from "./citations";

interface ChatMessageItemProps {
  message: ChatMessage;
  onOpenDocument: (target: ViewerTarget) => void;
  registerRef: (id: string, el: HTMLElement | null) => void;
}

function ChatMessageItem({
  message,
  onOpenDocument,
  registerRef,
}: ChatMessageItemProps) {
  const { t } = useI18n();
  const liveContent = useStreamingContent(message.id);
  const content = message.streaming ? liveContent : message.content;

  const setRef: RefCallback<HTMLElement> = useCallback(
    (el) => registerRef(message.id, el),
    [message.id, registerRef],
  );

  return (
    <article
      ref={setRef}
      className={`message ${message.role}`}
    >
      <div className="message-avatar">
        {message.role === "assistant" ? (
          <AllDocsIcon size={28} />
        ) : (
          t("chat.userAvatar")
        )}
      </div>
      <div className="message-body">
        {message.role === "assistant" &&
        ((message.agentSteps?.length ?? 0) > 0 || message.agentRunning) ? (
          <AgentSteps
            steps={message.agentSteps ?? []}
            running={message.agentRunning}
          />
        ) : null}
        <div className="message-content">
          {message.role === "assistant" ? (
            <MessageContent
              content={content}
              citations={message.citations ?? []}
              embeds={message.embeds ?? []}
              streaming={message.streaming}
              onOpenDocument={onOpenDocument}
            />
          ) : (
            message.content
          )}
          {message.streaming ? <span className="cursor">▍</span> : null}
        </div>
      </div>
    </article>
  );
}

export default memo(ChatMessageItem);
