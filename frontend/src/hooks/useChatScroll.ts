import { useCallback, useEffect, useRef, useState } from "react";

export function useChatScroll() {
  const chatAreaRef = useRef<HTMLDivElement>(null);
  const messageRefs = useRef<Map<string, HTMLElement>>(new Map());
  const spacerRef = useRef<HTMLDivElement>(null);
  const [scrollTargetId, setScrollTargetId] = useState<string | null>(null);

  const scrollUserMessageToTop = useCallback((userMessageId: string) => {
    const messageEl = messageRefs.current.get(userMessageId);
    if (!messageEl) return;
    messageEl.scrollIntoView({ block: "start", behavior: "instant" });
  }, []);

  useEffect(() => {
    if (!scrollTargetId) return;

    const layoutAndScroll = () => {
      const container = chatAreaRef.current;
      const messageEl = messageRefs.current.get(scrollTargetId);
      const spacer = spacerRef.current;
      if (!messageEl) return false;

      if (container && spacer) {
        const topGap =
          parseFloat(
            getComputedStyle(document.documentElement).getPropertyValue(
              "--chat-content-top",
            ),
          ) || 32;
        const room =
          container.clientHeight -
          messageEl.getBoundingClientRect().height -
          topGap -
          24;
        spacer.style.minHeight = `${Math.max(room, 0)}px`;
      }

      scrollUserMessageToTop(scrollTargetId);
      setScrollTargetId(null);
      return true;
    };

    requestAnimationFrame(() => {
      if (layoutAndScroll()) return;
      requestAnimationFrame(() => {
        layoutAndScroll();
      });
    });
  }, [scrollTargetId, scrollUserMessageToTop]);

  const registerMessageRef = useCallback((id: string, el: HTMLElement | null) => {
    if (el) messageRefs.current.set(id, el);
    else messageRefs.current.delete(id);
  }, []);

  const resetSpacer = useCallback(() => {
    if (spacerRef.current) spacerRef.current.style.minHeight = "";
  }, []);

  return {
    chatAreaRef,
    spacerRef,
    scrollTargetId,
    setScrollTargetId,
    registerMessageRef,
    resetSpacer,
  };
}
