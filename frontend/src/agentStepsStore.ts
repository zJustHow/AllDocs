import { useSyncExternalStore } from "react";
import {
  createExternalStoreHook,
  createExternalStoreNotifier,
  createMapStore,
} from "./externalStore";
import { appendAgentThoughtDelta, upsertAgentStep } from "./agentStepUtils";
import type { AgentStepEvent, AgentThoughtDelta, ChatMessage } from "./types";

const EMPTY_STEPS: AgentStepEvent[] = [];
const notifier = createExternalStoreNotifier();
const stepsStore = createMapStore<AgentStepEvent[]>(notifier);
const runningStore = createMapStore<boolean>(notifier);

export function initAgentSteps(messageId: string): void {
  stepsStore.init(messageId, []);
  runningStore.set(messageId, true);
}

export function hasAgentStepsSession(messageId: string): boolean {
  return stepsStore.has(messageId);
}

export function getAgentSteps(messageId: string): AgentStepEvent[] {
  return stepsStore.get(messageId, EMPTY_STEPS);
}

export function isAgentRunning(messageId: string): boolean {
  return runningStore.get(messageId, false);
}

export function setAgentRunning(messageId: string, running: boolean): void {
  if (runningStore.get(messageId, false) === running) return;
  runningStore.set(messageId, running);
}

export function appendAgentSteps(messageId: string, steps: AgentStepEvent[]): void {
  if (!steps.length) return;
  let next = stepsStore.get(messageId, EMPTY_STEPS);
  for (const step of steps) {
    next = upsertAgentStep(next, step);
  }
  stepsStore.set(messageId, next);
}

export function appendAgentThoughtDeltas(
  messageId: string,
  deltas: AgentThoughtDelta[],
): void {
  if (!deltas.length) return;
  let next = stepsStore.get(messageId, EMPTY_STEPS);
  for (const delta of deltas) {
    next = appendAgentThoughtDelta(next, delta);
  }
  stepsStore.set(messageId, next);
}

export function clearAgentSteps(messageId: string): AgentStepEvent[] {
  const steps = stepsStore.get(messageId, EMPTY_STEPS);
  stepsStore.delete(messageId);
  runningStore.delete(messageId);
  return steps;
}

export const subscribeAgentSteps = notifier.subscribe;

const useAgentSteps = createExternalStoreHook(
  notifier.subscribe,
  getAgentSteps,
  EMPTY_STEPS,
);

const useAgentRunning = createExternalStoreHook(
  notifier.subscribe,
  isAgentRunning,
  false,
);

export function useMessageAgentSteps(
  message: Pick<ChatMessage, "id" | "agentSteps" | "agentRunning">,
): { steps: AgentStepEvent[]; running: boolean } {
  const sessionActive = useSyncExternalStore(
    subscribeAgentSteps,
    () => hasAgentStepsSession(message.id),
    () => false,
  );
  const liveSteps = useAgentSteps(message.id);
  const liveRunning = useAgentRunning(message.id);

  if (sessionActive) {
    return { steps: liveSteps, running: liveRunning };
  }

  return {
    steps: message.agentSteps ?? [],
    running: message.agentRunning ?? false,
  };
}
