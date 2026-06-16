import { useVirtualizer } from "@tanstack/react-virtual";
import { memo, useEffect, type RefObject } from "react";
import ChatMessageItem from "./ChatMessageItem";
import type { ChatMessage } from "./types";
import type { ViewerTarget } from "./citations";

const ESTIMATED_MESSAGE_HEIGHT = 140;

interface MessageListProps {
  messages: ChatMessage[];
  scrollRef: RefObject<HTMLDivElement | null>;
  scrollTargetId: string | null;
  onOpenDocument: (target: ViewerTarget) => void;
  registerRef: (id: string, el: HTMLElement | null) => void;
  spacerRef: RefObject<HTMLDivElement | null>;
}

function MessageList({
  messages,
  scrollRef,
  scrollTargetId,
  onOpenDocument,
  registerRef,
  spacerRef,
}: MessageListProps) {
  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ESTIMATED_MESSAGE_HEIGHT,
    overscan: 5,
  });

  useEffect(() => {
    if (!scrollTargetId) return;
    const index = messages.findIndex((message) => message.id === scrollTargetId);
    if (index < 0) return;

    requestAnimationFrame(() => {
      virtualizer.scrollToIndex(index, { align: "start" });
    });
    // scrollTargetId is the only intentional trigger; messages/virtualizer are read at fire time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollTargetId]);

  return (
    <section className="messages">
      <div
        className="messages-virtual-list"
        style={{ height: `${virtualizer.getTotalSize()}px` }}
      >
        {virtualizer.getVirtualItems().map((item) => {
          const message = messages[item.index];
          return (
            <div
              key={message.id}
              data-index={item.index}
              ref={virtualizer.measureElement}
              className="messages-virtual-row"
              style={{ transform: `translateY(${item.start}px)` }}
            >
              <ChatMessageItem
                message={message}
                onOpenDocument={onOpenDocument}
                registerRef={registerRef}
              />
            </div>
          );
        })}
      </div>
      <div
        ref={spacerRef}
        className="message-scroll-spacer"
        aria-hidden="true"
      />
    </section>
  );
}

export default memo(MessageList);
