import type { AgentStepEvent, AgentThoughtDelta } from "./types";

export function parseAgentStepPayload(payload: {
  type: string;
  [key: string]: unknown;
}): AgentStepEvent | null {
  if (payload.type !== "agent_step" && payload.type !== "agent_step_start") {
    return null;
  }
  return {
    step: payload.step as number,
    thought: (payload.thought as string) ?? "",
    reasoning: (payload.reasoning as string) ?? "",
    action: (payload.action as string) ?? "",
    action_input: (payload.action_input as Record<string, unknown>) ?? {},
    observation: (payload.observation as string) ?? "",
    evidence_count: payload.evidence_count as number | undefined,
    status: payload.type === "agent_step_start" ? "running" : "done",
  };
}

export function upsertAgentStep(
  steps: AgentStepEvent[],
  step: AgentStepEvent,
): AgentStepEvent[] {
  const index = steps.findIndex((item) => item.step === step.step);
  if (index >= 0) {
    const next = [...steps];
    next[index] = { ...next[index], ...step };
    return next;
  }
  return [...steps, step];
}

export function appendAgentThoughtDelta(
  steps: AgentStepEvent[],
  { step, field, delta }: AgentThoughtDelta,
): AgentStepEvent[] {
  const index = steps.findIndex((item) => item.step === step);
  const key = field === "reasoning" ? "reasoning" : "thought";

  if (index >= 0) {
    const next = [...steps];
    const current = next[index];
    next[index] = {
      ...current,
      [key]: `${current[key] ?? ""}${delta}`,
    };
    return next;
  }

  return [
    ...steps,
    {
      step,
      thought: field === "content" ? delta : "",
      reasoning: field === "reasoning" ? delta : "",
      action: "planning",
      action_input: {},
      observation: "",
      status: "running",
    },
  ];
}
