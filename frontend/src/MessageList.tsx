import { memo, type RefObject } from "react";
import type { ViewerTarget } from "./citations";
import ChatMessageItem from "./ChatMessageItem";
import type { ChatMessage } from "./types";

interface MessageListProps {
  messages: ChatMessage[];
  scrollRef: RefObject<HTMLDivElement | null>;
  onOpenDocument: (target: ViewerTarget) => void;
  registerRef: (id: string, el: HTMLElement | null) => void;
  spacerRef: RefObject<HTMLDivElement | null>;
}

function MessageList({
  messages,
  scrollRef,
  onOpenDocument,
  registerRef,
  spacerRef,
}: MessageListProps) {
  return (
    <section className="messages">
      {messages.map((message) => (
        <ChatMessageItem
          key={message.id}
          message={message}
          onOpenDocument={onOpenDocument}
          registerRef={registerRef}
          scrollContainerRef={scrollRef}
        />
      ))}
      <div
        ref={spacerRef}
        className="message-scroll-spacer"
        aria-hidden="true"
      />
    </section>
  );
}

export default memo(MessageList);
