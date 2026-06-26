/** @vitest-environment jsdom */
import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  hideFloatingScrollbars,
  hideFloatingScrollbarsAfterLayout,
  suppressChatFloatingScrollbars,
  useAutoHideScrollbars,
} from "./useAutoHideScrollbars";

function Harness() {
  useAutoHideScrollbars();
  return <div data-testid="scroller" style={{ overflow: "auto" }} />;
}

function NestedHarness() {
  useAutoHideScrollbars();
  return (
    <div data-testid="vertical" style={{ overflowY: "auto" }}>
      <div data-testid="horizontal" style={{ overflowX: "auto" }} />
    </div>
  );
}

function EmptyChatHarness() {
  useAutoHideScrollbars();
  return (
    <div data-testid="scrollable-parent" style={{ overflow: "auto" }}>
      <div className="chat-area-empty" data-testid="empty-chat">
        <div data-testid="welcome" />
      </div>
    </div>
  );
}

function CitationHarness() {
  useAutoHideScrollbars();
  return (
    <button type="button" className="citation-link" data-testid="citation">
      [1]
    </button>
  );
}

function ChatAndViewerHarness() {
  useAutoHideScrollbars();
  return (
    <>
      <div className="chat-area" data-testid="chat" style={{ overflowY: "auto" }} />
      <div className="doc-viewer" data-testid="viewer-shell">
        <div data-testid="viewer" style={{ overflowY: "auto" }} />
      </div>
    </>
  );
}

const rect = {
  top: 0,
  right: 100,
  bottom: 100,
  left: 0,
  width: 100,
  height: 100,
  x: 0,
  y: 0,
  toJSON: () => ({}),
};

describe("useAutoHideScrollbars", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows a scrollbar while scrolling and hides it after inactivity", () => {
    vi.useFakeTimers();
    const { getByTestId } = render(<Harness />);
    const scroller = getByTestId("scroller");

    Object.defineProperties(scroller, {
      clientHeight: { value: 100, configurable: true },
      scrollHeight: { value: 300, configurable: true },
    });

    fireEvent.scroll(scroller);
    const floatingBar = document.querySelector(".floating-scrollbar--vertical");
    expect(floatingBar).toHaveClass("is-visible");

    act(() => vi.advanceTimersByTime(799));
    expect(floatingBar).toHaveClass("is-visible");

    act(() => vi.advanceTimersByTime(1));
    expect(floatingBar).not.toHaveClass("is-visible");
  });

  it("hides visible scrollbars immediately when requested", () => {
    vi.useFakeTimers();
    const { getByTestId } = render(<Harness />);
    const scroller = getByTestId("scroller");

    Object.defineProperties(scroller, {
      clientHeight: { value: 100, configurable: true },
      scrollHeight: { value: 300, configurable: true },
    });

    fireEvent.scroll(scroller);
    const floatingBar = document.querySelector(".floating-scrollbar--vertical");
    expect(floatingBar).toHaveClass("is-visible");

    hideFloatingScrollbars();

    expect(floatingBar).not.toHaveClass("is-visible");
    act(() => vi.advanceTimersByTime(800));
    expect(floatingBar).not.toHaveClass("is-visible");
  });

  it("hides scrollbars again after layout events can make them visible", () => {
    let frameCallback: FrameRequestCallback | null = null;
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((callback: FrameRequestCallback) => {
        frameCallback = callback;
        return 1;
      }),
    );
    const { getByTestId } = render(<Harness />);
    const scroller = getByTestId("scroller");

    Object.defineProperties(scroller, {
      clientHeight: { value: 100, configurable: true },
      scrollHeight: { value: 300, configurable: true },
    });

    fireEvent.scroll(scroller);
    const floatingBar = document.querySelector(".floating-scrollbar--vertical");
    expect(floatingBar).toHaveClass("is-visible");

    hideFloatingScrollbarsAfterLayout();
    expect(floatingBar).not.toHaveClass("is-visible");

    fireEvent.scroll(scroller);
    expect(floatingBar).toHaveClass("is-visible");

    act(() => frameCallback?.(0));
    expect(floatingBar).not.toHaveClass("is-visible");
  });

  it("suppresses chat scrollbars during viewer layout transitions only", () => {
    vi.useFakeTimers();
    const { getByTestId } = render(<ChatAndViewerHarness />);
    const chat = getByTestId("chat");
    const viewer = getByTestId("viewer");

    Object.defineProperties(chat, {
      clientHeight: { value: 100, configurable: true },
      scrollHeight: { value: 300, configurable: true },
    });
    Object.defineProperties(viewer, {
      clientHeight: { value: 100, configurable: true },
      scrollHeight: { value: 300, configurable: true },
    });

    suppressChatFloatingScrollbars(600);

    fireEvent.scroll(chat);
    expect(
      Array.from(document.querySelectorAll(".floating-scrollbar.is-visible")),
    ).toHaveLength(0);

    fireEvent.scroll(viewer);
    expect(
      Array.from(
        document.querySelectorAll(".floating-scrollbar--viewer.is-visible"),
      ).length,
    ).toBeGreaterThan(0);

    act(() => vi.advanceTimersByTime(600));
    fireEvent.scroll(chat);

    expect(
      Array.from(document.querySelectorAll(".floating-scrollbar.is-visible")).some(
        (bar) => !bar.classList.contains("floating-scrollbar--viewer"),
      ),
    ).toBe(true);
  });

  it("does not activate a horizontal child for vertical wheel input", () => {
    const { getByTestId } = render(<NestedHarness />);
    const vertical = getByTestId("vertical");
    const horizontal = getByTestId("horizontal");

    Object.defineProperties(vertical, {
      clientHeight: { value: 100, configurable: true },
      scrollHeight: { value: 300, configurable: true },
    });
    Object.defineProperties(horizontal, {
      clientWidth: { value: 100, configurable: true },
      scrollWidth: { value: 300, configurable: true },
    });
    vi.spyOn(vertical, "getBoundingClientRect").mockReturnValue(rect);
    vi.spyOn(horizontal, "getBoundingClientRect").mockReturnValue(rect);

    fireEvent.wheel(horizontal, { deltaX: 20 });
    expect(
      Array.from(document.querySelectorAll<HTMLElement>(".floating-scrollbar--horizontal")).some(
        (bar) => bar.style.display === "block" && bar.classList.contains("is-visible"),
      ),
    ).toBe(true);

    fireEvent.wheel(horizontal, { deltaY: 20 });

    expect(
      Array.from(document.querySelectorAll<HTMLElement>(".floating-scrollbar--vertical")).some(
        (bar) => bar.style.display === "block" && bar.classList.contains("is-visible"),
      ),
    ).toBe(true);
    expect(
      Array.from(document.querySelectorAll<HTMLElement>(".floating-scrollbar--horizontal")).some(
        (bar) => bar.style.display === "block" && bar.classList.contains("is-visible"),
      ),
    ).toBe(false);
  });

  it("does not activate an ancestor scrollbar for wheel input in an empty chat", () => {
    const { getByTestId } = render(<EmptyChatHarness />);
    const parent = getByTestId("scrollable-parent");
    const welcome = getByTestId("welcome");

    Object.defineProperties(parent, {
      clientHeight: { value: 100, configurable: true },
      scrollHeight: { value: 300, configurable: true },
    });

    fireEvent.wheel(welcome, { deltaY: 20 });

    expect(document.querySelector(".floating-scrollbar.is-visible")).not.toBeInTheDocument();
  });

  it("does not show a floating scrollbar for citation buttons", () => {
    const { getByTestId } = render(<CitationHarness />);
    const citation = getByTestId("citation");

    Object.defineProperties(citation, {
      clientWidth: { value: 16, configurable: true },
      scrollWidth: { value: 24, configurable: true },
    });
    vi.spyOn(citation, "getBoundingClientRect").mockReturnValue({
      ...rect,
      right: 24,
      bottom: 20,
      width: 24,
      height: 20,
    });

    fireEvent.pointerMove(citation, { clientX: 20, clientY: 10 });
    fireEvent.wheel(citation, { deltaX: 20 });

    expect(document.querySelector(".floating-scrollbar.is-visible")).not.toBeInTheDocument();
  });

  it("shows the vertical scrollbar when the pointer moves over its edge", () => {
    const { getByTestId } = render(<Harness />);
    const scroller = getByTestId("scroller");

    Object.defineProperties(scroller, {
      clientHeight: { value: 100, configurable: true },
      scrollHeight: { value: 300, configurable: true },
    });
    vi.spyOn(scroller, "getBoundingClientRect").mockReturnValue(rect);

    fireEvent.pointerMove(scroller, { clientX: 96, clientY: 50 });

    const floatingBar = document.querySelector<HTMLElement>(".floating-scrollbar--vertical");
    expect(floatingBar).toHaveClass("is-visible");
    expect(floatingBar?.style.display).toBe("block");
  });

  it("shows the horizontal scrollbar when the pointer moves over its edge", () => {
    const { getByTestId } = render(<Harness />);
    const scroller = getByTestId("scroller");

    Object.defineProperties(scroller, {
      clientWidth: { value: 100, configurable: true },
      scrollWidth: { value: 300, configurable: true },
    });
    vi.spyOn(scroller, "getBoundingClientRect").mockReturnValue(rect);

    fireEvent.pointerMove(scroller, { clientX: 50, clientY: 96 });

    const floatingBar = document.querySelector<HTMLElement>(".floating-scrollbar--horizontal");
    expect(floatingBar).toHaveClass("is-visible");
    expect(floatingBar?.style.display).toBe("block");
  });

  it("keeps a hovered image scrollbar visible when the pointer is over its thumb", () => {
    vi.useFakeTimers();
    const { getByTestId } = render(<Harness />);
    const scroller = getByTestId("scroller");

    Object.defineProperties(scroller, {
      clientWidth: { value: 100, configurable: true },
      scrollWidth: { value: 300, configurable: true },
    });
    vi.spyOn(scroller, "getBoundingClientRect").mockReturnValue(rect);

    fireEvent.pointerMove(scroller, { clientX: 50, clientY: 96 });
    const floatingBar = document.querySelector<HTMLElement>(
      ".floating-scrollbar--horizontal",
    );
    expect(floatingBar).toHaveClass("is-visible");

    act(() => vi.advanceTimersByTime(700));
    fireEvent.pointerMove(floatingBar!, { clientX: 50, clientY: 96 });
    act(() => vi.advanceTimersByTime(101));

    expect(floatingBar).toHaveClass("is-visible");
  });

  it("drags the vertical floating scrollbar thumb", () => {
    const { getByTestId } = render(<Harness />);
    const scroller = getByTestId("scroller");

    Object.defineProperties(scroller, {
      clientHeight: { value: 100, configurable: true },
      scrollHeight: { value: 300, configurable: true },
    });
    vi.spyOn(scroller, "getBoundingClientRect").mockReturnValue(rect);

    fireEvent.scroll(scroller);
    const floatingBar = document.querySelector<HTMLElement>(".floating-scrollbar--vertical");
    expect(floatingBar).not.toBeNull();
    vi.spyOn(floatingBar!, "getBoundingClientRect").mockReturnValue({
      ...rect,
      height: Number.parseFloat(floatingBar!.style.height),
    });

    fireEvent.pointerDown(floatingBar!, { clientY: 0, pointerId: 1 });
    fireEvent.pointerMove(document, { clientY: 33.333, pointerId: 1 });

    expect(scroller.scrollTop).toBeCloseTo(100, 0);
  });

  it("drags the horizontal floating scrollbar thumb", () => {
    const { getByTestId } = render(<Harness />);
    const scroller = getByTestId("scroller");

    Object.defineProperties(scroller, {
      clientWidth: { value: 100, configurable: true },
      scrollWidth: { value: 300, configurable: true },
    });
    vi.spyOn(scroller, "getBoundingClientRect").mockReturnValue(rect);

    fireEvent.scroll(scroller);
    const floatingBar = document.querySelector<HTMLElement>(".floating-scrollbar--horizontal");
    expect(floatingBar).not.toBeNull();
    vi.spyOn(floatingBar!, "getBoundingClientRect").mockReturnValue({
      ...rect,
      width: Number.parseFloat(floatingBar!.style.width),
    });

    fireEvent.pointerDown(floatingBar!, { clientX: 0, pointerId: 1 });
    fireEvent.pointerMove(document, { clientX: 33.333, pointerId: 1 });

    expect(scroller.scrollLeft).toBeCloseTo(100, 0);
  });
});
