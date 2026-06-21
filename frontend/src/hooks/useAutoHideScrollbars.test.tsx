/** @vitest-environment jsdom */
import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAutoHideScrollbars } from "./useAutoHideScrollbars";

function Harness() {
  useAutoHideScrollbars();
  return <div data-testid="scroller" />;
}

function NestedHarness() {
  useAutoHideScrollbars();
  return (
    <div data-testid="vertical">
      <div data-testid="horizontal" />
    </div>
  );
}

describe("useAutoHideScrollbars", () => {
  afterEach(() => vi.useRealTimers());

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

  it("does not activate a horizontal child for vertical wheel input", () => {
    const { getByTestId } = render(<NestedHarness />);
    const vertical = getByTestId("vertical");
    const horizontal = getByTestId("horizontal");
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

    Object.defineProperties(vertical, {
      clientHeight: { value: 100, configurable: true },
      scrollHeight: { value: 300, configurable: true },
    });
    Object.defineProperties(horizontal, {
      clientWidth: { value: 100, configurable: true },
      scrollWidth: { value: 300, configurable: true },
    });
    vi.spyOn(vertical, "getBoundingClientRect").mockReturnValue(rect);

    fireEvent.wheel(horizontal, { deltaY: 20 });

    expect(document.querySelector<HTMLElement>(".floating-scrollbar--vertical")?.style.display).toBe("block");
    expect(document.querySelector<HTMLElement>(".floating-scrollbar--horizontal")?.style.display).toBe("none");
  });
});
