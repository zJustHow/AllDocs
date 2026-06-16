import type { AgentStepEvent } from "./types";

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
