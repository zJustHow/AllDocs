import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createDeltaBatcher, createEventBatcher } from "./streamBatch";

describe("createEventBatcher", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("flushes queued items after the delay", () => {
    const append = vi.fn();
    const batcher = createEventBatcher<number>(append, 50);

    batcher.push(1);
    batcher.push(2);
    expect(append).not.toHaveBeenCalled();

    vi.advanceTimersByTime(50);

    expect(append).toHaveBeenCalledWith([1, 2]);
  });

  it("flushes immediately when flush is called", () => {
    const append = vi.fn();
    const batcher = createEventBatcher<string>(append, 50);

    batcher.push("a");
    batcher.flush();

    expect(append).toHaveBeenCalledWith(["a"]);
  });
});

describe("createDeltaBatcher", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("concatenates deltas before flushing", () => {
    const append = vi.fn();
    const batcher = createDeltaBatcher(append);

    batcher.push("hel");
    batcher.push("lo");
    vi.advanceTimersByTime(50);

    expect(append).toHaveBeenCalledWith("hello");
  });
});
