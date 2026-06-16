import { memo, useMemo, useState, type RefObject } from "react";
import ChatMessageItem from "./ChatMessageItem";
import { useI18n } from "./i18n";
import type { ChatMessage } from "./types";
import type { ViewerTarget } from "./citations";

const VISIBLE_MESSAGE_LIMIT = 40;

interface MessageListProps {
  messages: ChatMessage[];
  onOpenDocument: (target: ViewerTarget) => void;
  registerRef: (id: string, el: HTMLElement | null) => void;
  spacerRef: RefObject<HTMLDivElement | null>;
}

function MessageList({
  messages,
  onOpenDocument,
  registerRef,
  spacerRef,
}: MessageListProps) {
  const { t } = useI18n();
  const [showAll, setShowAll] = useState(false);

  const hiddenCount = Math.max(0, messages.length - VISIBLE_MESSAGE_LIMIT);
  const visibleMessages = useMemo(() => {
    if (showAll || hiddenCount === 0) return messages;
    return messages.slice(-VISIBLE_MESSAGE_LIMIT);
  }, [messages, showAll, hiddenCount]);

  return (
    <section className="messages">
      {hiddenCount > 0 && !showAll ? (
        <button
          type="button"
          className="messages-show-earlier"
          onClick={() => setShowAll(true)}
        >
          {t("chat.showEarlier", { count: hiddenCount })}
        </button>
      ) : null}
      {visibleMessages.map((msg) => (
        <ChatMessageItem
          key={msg.id}
          message={msg}
          onOpenDocument={onOpenDocument}
          registerRef={registerRef}
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
