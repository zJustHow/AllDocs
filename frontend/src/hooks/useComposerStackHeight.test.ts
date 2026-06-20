/** @vitest-environment jsdom */
import { act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHookWithI18n } from "./testUtils";
import {
  readComposerStackHeight,
  useComposerStackHeight,
} from "./useComposerStackHeight";

describe("useComposerStackHeight", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("writes the measured composer height onto chat-shell", () => {
    document.body.innerHTML = `
      <div class="chat-shell">
        <div class="main-bottom" style="height: 120px"></div>
      </div>
    `;
    const composer = document.querySelector(".main-bottom") as HTMLDivElement;
    const shell = document.querySelector(".chat-shell") as HTMLDivElement;
    Object.defineProperty(composer, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ height: 120 }),
    });

    const ref = { current: composer };
    renderHookWithI18n(() => useComposerStackHeight(ref, "sync"));

    expect(shell.style.getPropertyValue("--composer-stack-height")).toBe(
      "120px",
    );
    expect(readComposerStackHeight(composer)).toBe(120);
  });

  it("re-syncs when the sync key changes", () => {
    document.body.innerHTML = `
      <div class="chat-shell">
        <div class="main-bottom"></div>
      </div>
    `;
    const composer = document.querySelector(".main-bottom") as HTMLDivElement;
    const shell = document.querySelector(".chat-shell") as HTMLDivElement;
    let height = 90;
    Object.defineProperty(composer, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ height }),
    });

    const ref = { current: composer };
    const { rerender } = renderHookWithI18n(
      ({ syncKey }: { syncKey: string }) => useComposerStackHeight(ref, syncKey),
      { initialProps: { syncKey: "a" } },
    );

    expect(shell.style.getPropertyValue("--composer-stack-height")).toBe("90px");

    height = 140;
    act(() => {
      rerender({ syncKey: "b" });
    });

    expect(shell.style.getPropertyValue("--composer-stack-height")).toBe(
      "140px",
    );
  });
});
