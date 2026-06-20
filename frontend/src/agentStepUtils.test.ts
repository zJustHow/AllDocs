import { describe, expect, it } from "vitest";
import {
  appendAgentThoughtDelta,
  parseAgentStepPayload,
  upsertAgentStep,
} from "./agentStepUtils";
import type { AgentStepEvent } from "./types";

describe("parseAgentStepPayload", () => {
  it("returns null for unrelated event types", () => {
    expect(parseAgentStepPayload({ type: "delta", text: "x" })).toBeNull();
  });

  it("parses completed agent step events", () => {
    const step = parseAgentStepPayload({
      type: "agent_step",
      step: 2,
      thought: "Searching",
      action: "search",
      action_input: { q: "motor" },
      observation: "Found 3 docs",
      evidence_count: 3,
    });

    expect(step).toEqual({
      step: 2,
      thought: "Searching",
      reasoning: "",
      action: "search",
      action_input: { q: "motor" },
      observation: "Found 3 docs",
      evidence_count: 3,
      status: "done",
    });
  });

  it("marks start events as running", () => {
    const step = parseAgentStepPayload({ type: "agent_step_start", step: 1 });
    expect(step?.status).toBe("running");
  });
});

describe("upsertAgentStep", () => {
  const existing: AgentStepEvent = {
    step: 1,
    thought: "old",
    action: "plan",
    action_input: {},
    observation: "",
    status: "running",
  };

  it("updates an existing step by step number", () => {
    const next = upsertAgentStep([existing], {
      ...existing,
      thought: "new",
      status: "done",
    });

    expect(next).toHaveLength(1);
    expect(next[0].thought).toBe("new");
    expect(next[0].status).toBe("done");
  });

  it("appends a new step when step number is unseen", () => {
    const next = upsertAgentStep([existing], {
      step: 2,
      thought: "second",
      action: "search",
      action_input: {},
      observation: "",
      status: "running",
    });

    expect(next).toHaveLength(2);
    expect(next[1].step).toBe(2);
  });
});

describe("appendAgentThoughtDelta", () => {
  it("appends reasoning delta to an existing step", () => {
    const steps: AgentStepEvent[] = [
      {
        step: 1,
        thought: "plan",
        reasoning: "because",
        action: "plan",
        action_input: {},
        observation: "",
        status: "running",
      },
    ];

    const next = appendAgentThoughtDelta(steps, {
      step: 1,
      field: "reasoning",
      delta: " more",
    });

    expect(next[0].reasoning).toBe("because more");
  });

  it("creates a running step when delta arrives before step payload", () => {
    const next = appendAgentThoughtDelta([], {
      step: 3,
      field: "content",
      delta: "Thinking",
    });

    expect(next).toEqual([
      {
        step: 3,
        thought: "Thinking",
        reasoning: "",
        action: "planning",
        action_input: {},
        observation: "",
        status: "running",
      },
    ]);
  });
});
