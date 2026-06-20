import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  appendStreamingContent,
  clearStreamingContent,
  getStreamingContent,
  initStreamingContent,
  useStreamingContent,
} from "./streamingContent";

describe("streamingContent store", () => {
  it("initializes, appends, reads, and clears message content", () => {
    initStreamingContent("msg-1");
    expect(getStreamingContent("msg-1")).toBe("");

    appendStreamingContent("msg-1", "hel");
    appendStreamingContent("msg-1", "lo");
    expect(getStreamingContent("msg-1")).toBe("hello");

    clearStreamingContent("msg-1");
    expect(getStreamingContent("msg-1")).toBe("");
  });

  it("returns empty string for unknown message ids", () => {
    expect(getStreamingContent("missing")).toBe("");
  });
});

/** @vitest-environment jsdom */
describe("useStreamingContent", () => {
  it("subscribes to streaming content updates", () => {
    initStreamingContent("msg-hook");
    const { result } = renderHook(() => useStreamingContent("msg-hook"));

    expect(result.current).toBe("");

    act(() => {
      appendStreamingContent("msg-hook", "stream");
    });
    expect(result.current).toBe("stream");

    act(() => {
      clearStreamingContent("msg-hook");
    });
    expect(result.current).toBe("");
  });
});
