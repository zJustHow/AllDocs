import { useEffect } from "react";

const HIDE_DELAY_MS = 800;
const MIN_THUMB_SIZE = 24;
const HOVER_HIT_SLOP = 12;
const HIDE_SCROLLBARS_EVENT = "alldocs:hide-floating-scrollbars";

interface FloatingBars {
  horizontal: HTMLDivElement;
  vertical: HTMLDivElement;
}

interface DragState {
  element: HTMLElement;
  bars: FloatingBars;
  axis: "horizontal" | "vertical";
  startPointer: number;
  startScroll: number;
  scrollRange: number;
  thumbTravel: number;
}

function isScrollable(element: HTMLElement): boolean {
  if (element.classList.contains("chat-area-empty")) return false;
  return (
    canScrollOnAxis(element, "vertical") || canScrollOnAxis(element, "horizontal")
  );
}

function hasScrollableOverflow(
  element: HTMLElement,
  axis: "horizontal" | "vertical",
): boolean {
  if (element === document.scrollingElement) return true;
  const styles = window.getComputedStyle(element);
  const declared =
    axis === "vertical"
      ? styles.overflowY || styles.overflow
      : styles.overflowX || styles.overflow;
  const inline =
    axis === "vertical"
      ? element.style.overflowY || element.style.overflow
      : element.style.overflowX || element.style.overflow;
  return [declared, inline].some(
    (overflow) =>
      overflow === "auto" || overflow === "scroll" || overflow === "overlay",
  );
}

function canScrollOnAxis(element: HTMLElement, axis: "horizontal" | "vertical"): boolean {
  if (element.classList.contains("chat-area-empty")) return false;
  if (!hasScrollableOverflow(element, axis)) return false;
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
    let dragState: DragState | null = null;
    let hoverElement: HTMLElement | null = null;

    const scheduleHide = (element: HTMLElement, bars: FloatingBars) => {
      const previousTimer = hideTimers.get(element);
      if (previousTimer !== undefined) window.clearTimeout(previousTimer);
      const timer = window.setTimeout(() => {
        if (dragState?.element === element) return;
        bars.horizontal.classList.remove("is-visible");
        bars.vertical.classList.remove("is-visible");
        hideTimers.delete(element);
      }, HIDE_DELAY_MS);
      hideTimers.set(element, timer);
    };

    const getBars = (element: HTMLElement): FloatingBars => {
      const existing = barsByElement.get(element);
      if (existing) return existing;
      const viewer = element.closest(".doc-viewer") !== null;
      const bars = {
        horizontal: createBar("horizontal", viewer),
        vertical: createBar("vertical", viewer),
      };
      bars.horizontal.addEventListener("pointerdown", (event) =>
        startDrag(element, bars, "horizontal", event),
      );
      bars.vertical.addEventListener("pointerdown", (event) =>
        startDrag(element, bars, "vertical", event),
      );
      bars.horizontal.addEventListener("pointerenter", () => keepVisible(element, bars));
      bars.vertical.addEventListener("pointerenter", () => keepVisible(element, bars));
      bars.horizontal.addEventListener("pointerleave", () => scheduleHide(element, bars));
      bars.vertical.addEventListener("pointerleave", () => scheduleHide(element, bars));
      barsByElement.set(element, bars);
      return bars;
    };

    const keepVisible = (element: HTMLElement, bars: FloatingBars) => {
      const previousTimer = hideTimers.get(element);
      if (previousTimer !== undefined) window.clearTimeout(previousTimer);
      hideTimers.delete(element);
      updateBars(element, bars);
      bars.horizontal.classList.add("is-visible");
      bars.vertical.classList.add("is-visible");
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

    const hideAllBars = () => {
      dragState = null;
      hoverElement = null;
      for (const timer of hideTimers.values()) window.clearTimeout(timer);
      hideTimers.clear();
      for (const bars of barsByElement.values()) {
        bars.horizontal.classList.remove("is-visible");
        bars.vertical.classList.remove("is-visible");
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

    function startDrag(
      element: HTMLElement,
      bars: FloatingBars,
      axis: "horizontal" | "vertical",
      event: PointerEvent,
    ) {
      const isRoot = element === document.scrollingElement;
      const rect = isRoot
        ? {
            width: window.innerWidth,
            height: window.innerHeight,
          }
        : element.getBoundingClientRect();
      const scrollRange =
        axis === "vertical"
          ? element.scrollHeight - element.clientHeight
          : element.scrollWidth - element.clientWidth;
      const thumbSize =
        axis === "vertical"
          ? bars.vertical.getBoundingClientRect().height
          : bars.horizontal.getBoundingClientRect().width;
      const trackSize = axis === "vertical" ? rect.height : rect.width;
      const thumbTravel = Math.max(0, trackSize - thumbSize);

      if (scrollRange <= 1 || thumbTravel <= 0) return;

      const previousTimer = hideTimers.get(element);
      if (previousTimer !== undefined) window.clearTimeout(previousTimer);
      hideTimers.delete(element);
      bars.horizontal.classList.add("is-visible");
      bars.vertical.classList.add("is-visible");

      dragState = {
        element,
        bars,
        axis,
        startPointer: axis === "vertical" ? event.clientY : event.clientX,
        startScroll: axis === "vertical" ? element.scrollTop : element.scrollLeft,
        scrollRange,
        thumbTravel,
      };
      event.preventDefault();
      event.currentTarget instanceof HTMLElement &&
        event.currentTarget.setPointerCapture?.(event.pointerId);
    }

    const showScrollbarForPointer = (event: PointerEvent) => {
      const eventPath = event.composedPath();
      const overFloatingBar = eventPath.some(
        (target): target is HTMLElement =>
          target instanceof HTMLElement &&
          target.classList.contains("floating-scrollbar"),
      );
      if (overFloatingBar && hoverElement && isScrollable(hoverElement)) {
        showScrollbar(hoverElement);
        return;
      }

      const scrollable = eventPath.find((target): target is HTMLElement => {
        if (!(target instanceof HTMLElement) || !isScrollable(target)) return false;
        const rect = target.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
        const insideX = event.clientX >= rect.left && event.clientX <= rect.right;
        const insideY = event.clientY >= rect.top && event.clientY <= rect.bottom;
        if (!insideX || !insideY) return false;
        const nearVertical =
          canScrollOnAxis(target, "vertical") &&
          event.clientX >= rect.right - HOVER_HIT_SLOP;
        const nearHorizontal =
          canScrollOnAxis(target, "horizontal") &&
          event.clientY >= rect.bottom - HOVER_HIT_SLOP;
        return nearVertical || nearHorizontal;
      });

      if (scrollable) {
        hoverElement = scrollable;
        showScrollbar(scrollable);
      }
    };

    const handlePointerMove = (event: PointerEvent) => {
      if (!dragState) {
        showScrollbarForPointer(event);
        return;
      }
      const pointer = dragState.axis === "vertical" ? event.clientY : event.clientX;
      const delta = pointer - dragState.startPointer;
      const nextScroll =
        dragState.startScroll + (delta / dragState.thumbTravel) * dragState.scrollRange;

      if (dragState.axis === "vertical") {
        dragState.element.scrollTop = Math.min(
          dragState.scrollRange,
          Math.max(0, nextScroll),
        );
      } else {
        dragState.element.scrollLeft = Math.min(
          dragState.scrollRange,
          Math.max(0, nextScroll),
        );
      }
      updateBars(dragState.element, dragState.bars);
      event.preventDefault();
    };

    const handlePointerUp = () => {
      if (!dragState) return;
      const { element, bars } = dragState;
      dragState = null;
      scheduleHide(element, bars);
    };

    const showScrollbar = (element: HTMLElement | null) => {
      if (!element || !isScrollable(element)) return;

      const bars = getBars(element);
      updateBars(element, bars);
      bars.horizontal.classList.add("is-visible");
      bars.vertical.classList.add("is-visible");

      if (dragState?.element !== element) scheduleHide(element, bars);
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
    document.addEventListener("pointermove", handlePointerMove);
    document.addEventListener("pointerup", handlePointerUp);
    document.addEventListener("pointercancel", handlePointerUp);
    document.addEventListener(HIDE_SCROLLBARS_EVENT, hideAllBars);
    window.addEventListener("resize", handleResize);

    return () => {
      document.removeEventListener("scroll", handleScroll, true);
      document.removeEventListener("wheel", handleWheel, true);
      document.removeEventListener("pointermove", handlePointerMove);
      document.removeEventListener("pointerup", handlePointerUp);
      document.removeEventListener("pointercancel", handlePointerUp);
      document.removeEventListener(HIDE_SCROLLBARS_EVENT, hideAllBars);
      window.removeEventListener("resize", handleResize);
      for (const timer of hideTimers.values()) window.clearTimeout(timer);
      for (const bars of barsByElement.values()) {
        bars.horizontal.remove();
        bars.vertical.remove();
      }
    };
  }, []);
}

export function hideFloatingScrollbars() {
  document.dispatchEvent(new Event(HIDE_SCROLLBARS_EVENT));
}
