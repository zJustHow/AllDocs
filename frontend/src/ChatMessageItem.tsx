import {
  memo,
  useCallback,
  useLayoutEffect,
  useRef,
  type RefCallback,
  type RefObject,
} from "react";
import AgentSteps from "./AgentSteps";
import { useMessageAgentSteps } from "./agentStepsStore";
import { followCursorInContainer } from "./followStreamingScroll";
import MessageContent from "./MessageContent";
import { useStreamingContent } from "./streamingContent";
import type { ViewerTarget } from "./citations";
import type { ChatMessage } from "./types";

interface ChatMessageItemProps {
  message: ChatMessage;
  onOpenDocument: (target: ViewerTarget) => void;
  registerRef: (id: string, el: HTMLElement | null) => void;
  scrollContainerRef: RefObject<HTMLDivElement | null>;
}

function ChatMessageItem({
  message,
  onOpenDocument,
  registerRef,
  scrollContainerRef,
}: ChatMessageItemProps) {
  const liveContent = useStreamingContent(message.id);
  const { steps: agentSteps, running: agentRunning } = useMessageAgentSteps(message);
  const content = message.streaming ? liveContent : message.content;
  const cursorRef = useRef<HTMLSpanElement>(null);

  const setRef: RefCallback<HTMLElement> = useCallback(
    (el) => registerRef(message.id, el),
    [message.id, registerRef],
  );

  useLayoutEffect(() => {
    if (!message.streaming) return;
    const container = scrollContainerRef.current;
    const cursor = cursorRef.current;
    if (!container || !cursor) return;

    const follow = () => followCursorInContainer(cursor, container);

    follow();
    // Virtual row height may settle one frame after content grows.
    requestAnimationFrame(follow);
  }, [
    liveContent,
    message.streaming,
    message.embeds?.length ?? 0,
    agentRunning,
    agentSteps.length,
    scrollContainerRef,
  ]);

  return (
    <article
      ref={setRef}
      className={`message ${message.role}`}
    >
      <div className="message-body">
        {message.role === "assistant" &&
        (agentSteps.length > 0 || agentRunning) ? (
          <AgentSteps
            steps={agentSteps}
            running={agentRunning}
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
          {message.streaming ? (
            <span ref={cursorRef} className="cursor">
              ▍
            </span>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export default memo(ChatMessageItem);
