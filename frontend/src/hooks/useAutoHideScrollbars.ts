import { useEffect } from "react";

const HIDE_DELAY_MS = 800;
const MIN_THUMB_SIZE = 24;

interface FloatingBars {
  horizontal: HTMLDivElement;
  vertical: HTMLDivElement;
}

function isScrollable(element: HTMLElement): boolean {
  if (element.classList.contains("chat-area-empty")) return false;
  return (
    element.scrollHeight > element.clientHeight + 1 ||
    element.scrollWidth > element.clientWidth + 1
  );
}

function canScrollOnAxis(element: HTMLElement, axis: "horizontal" | "vertical"): boolean {
  if (element.classList.contains("chat-area-empty")) return false;
  return axis === "vertical"
    ? element.scrollHeight > element.clientHeight + 1
    : element.scrollWidth > element.clientWidth + 1;
}

function createBar(axis: "horizontal" | "vertical", viewer: boolean): HTMLDivElement {
  const bar = document.createElement("div");
  bar.className = `floating-scrollbar floating-scrollbar--${axis}${viewer ? " floating-scrollbar--viewer" : ""}`;
  bar.setAttribute("aria-hidden", "true");
  document.body.appendChild(bar);
  return bar;
}

export function useAutoHideScrollbars() {
  useEffect(() => {
    const hideTimers = new Map<HTMLElement, number>();
    const barsByElement = new Map<HTMLElement, FloatingBars>();

    const getBars = (element: HTMLElement): FloatingBars => {
      const existing = barsByElement.get(element);
      if (existing) return existing;
      const viewer = element.closest(".doc-viewer") !== null;
      const bars = {
        horizontal: createBar("horizontal", viewer),
        vertical: createBar("vertical", viewer),
      };
      barsByElement.set(element, bars);
      return bars;
    };

    const hideDescendantBars = (container: HTMLElement) => {
      for (const [element, bars] of barsByElement) {
        if (element === container || !container.contains(element)) continue;
        bars.horizontal.classList.remove("is-visible");
        bars.vertical.classList.remove("is-visible");
        const timer = hideTimers.get(element);
        if (timer !== undefined) window.clearTimeout(timer);
        hideTimers.delete(element);
      }
    };

    const updateBars = (element: HTMLElement, bars: FloatingBars) => {
      const isRoot = element === document.scrollingElement;
      const rect = isRoot
        ? { top: 0, right: window.innerWidth, bottom: window.innerHeight, left: 0, width: window.innerWidth, height: window.innerHeight }
        : element.getBoundingClientRect();

      const verticalRange = element.scrollHeight - element.clientHeight;
      if (verticalRange > 1 && rect.height > 0) {
        const size = Math.max(MIN_THUMB_SIZE, (element.clientHeight / element.scrollHeight) * rect.height);
        const top = rect.top + (element.scrollTop / verticalRange) * Math.max(0, rect.height - size);
        Object.assign(bars.vertical.style, {
          display: "block",
          height: `${size}px`,
          left: `${rect.right - 7}px`,
          top: `${top}px`,
        });
      } else {
        bars.vertical.style.display = "none";
      }

      const horizontalRange = element.scrollWidth - element.clientWidth;
      if (horizontalRange > 1 && rect.width > 0) {
        const size = Math.max(MIN_THUMB_SIZE, (element.clientWidth / element.scrollWidth) * rect.width);
        const left = rect.left + (element.scrollLeft / horizontalRange) * Math.max(0, rect.width - size);
        Object.assign(bars.horizontal.style, {
          display: "block",
          left: `${left}px`,
          top: `${rect.bottom - 7}px`,
          width: `${size}px`,
        });
      } else {
        bars.horizontal.style.display = "none";
      }
    };

    const showScrollbar = (element: HTMLElement | null) => {
      if (!element || !isScrollable(element)) return;

      const bars = getBars(element);
      updateBars(element, bars);
      bars.horizontal.classList.add("is-visible");
      bars.vertical.classList.add("is-visible");

      const previousTimer = hideTimers.get(element);
      if (previousTimer !== undefined) window.clearTimeout(previousTimer);
      const timer = window.setTimeout(() => {
        bars.horizontal.classList.remove("is-visible");
        bars.vertical.classList.remove("is-visible");
        hideTimers.delete(element);
      }, HIDE_DELAY_MS);
      hideTimers.set(element, timer);
    };

    const handleScroll = (event: Event) => {
      const target = event.target;
      const scrollElement =
        target instanceof HTMLElement
          ? target
          : (document.scrollingElement as HTMLElement | null);
      if (scrollElement) hideDescendantBars(scrollElement);
      showScrollbar(scrollElement);
      for (const [element, bars] of barsByElement) {
        if (hideTimers.has(element)) updateBars(element, bars);
      }
    };

    const handleWheel = (event: WheelEvent) => {
      const eventPath = event.composedPath();
      const emptyChatArea = eventPath.find(
        (target): target is HTMLElement =>
          target instanceof HTMLElement && target.classList.contains("chat-area-empty"),
      );
      if (emptyChatArea) {
        const bars = barsByElement.get(emptyChatArea);
        bars?.horizontal.classList.remove("is-visible");
        bars?.vertical.classList.remove("is-visible");
        const timer = hideTimers.get(emptyChatArea);
        if (timer !== undefined) window.clearTimeout(timer);
        hideTimers.delete(emptyChatArea);
        return;
      }

      const axis = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? "vertical" : "horizontal";
      const scrollable = eventPath
        .find(
          (target): target is HTMLElement =>
            target instanceof HTMLElement && canScrollOnAxis(target, axis),
        );
      if (scrollable) hideDescendantBars(scrollable);
      showScrollbar(scrollable ?? null);
    };

    const handleResize = () => {
      for (const [element, bars] of barsByElement) updateBars(element, bars);
    };

    document.addEventListener("scroll", handleScroll, true);
    document.addEventListener("wheel", handleWheel, { capture: true, passive: true });
    window.addEventListener("resize", handleResize);

    return () => {
      document.removeEventListener("scroll", handleScroll, true);
      document.removeEventListener("wheel", handleWheel, true);
      window.removeEventListener("resize", handleResize);
      for (const timer of hideTimers.values()) window.clearTimeout(timer);
      for (const bars of barsByElement.values()) {
        bars.horizontal.remove();
        bars.vertical.remove();
      }
    };
  }, []);
}
