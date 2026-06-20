import type { ChatMessage } from "./types";

const MESSAGE_CHROME = 84;
const LINE_HEIGHT = 24;
const CHARS_PER_LINE = 52;
const AGENT_SUMMARY_HEIGHT = 42;
const AGENT_STEP_HEIGHT = 85;
const EMBED_FIGURE_HEIGHT = 300;
const EMBED_TABLE_HEIGHT = 340;
const EMBED_GALLERY_HEIGHT = 250;
const STREAMING_CURSOR_HEIGHT = 24;

function estimateTextHeight(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) return 0;

  let height = 0;
  for (const line of trimmed.split("\n")) {
    if (/^#{1,4}\s/.test(line)) {
      height += 36;
      continue;
    }
    if (!line.trim()) {
      height += 12;
      continue;
    }
    height += Math.max(1, Math.ceil(line.length / CHARS_PER_LINE)) * LINE_HEIGHT;
  }
  return height;
}

function estimateAgentStepsHeight(message: ChatMessage): number {
  const steps = message.agentSteps ?? [];
  if (steps.length === 0 && !message.agentRunning) return 0;

  if (!message.agentRunning) {
    return AGENT_SUMMARY_HEIGHT;
  }

  const visibleSteps = steps.filter(
    (step) => step.action !== "planning" || step.status === "running",
  );
  return (
    AGENT_SUMMARY_HEIGHT + 12 + Math.max(visibleSteps.length, 1) * AGENT_STEP_HEIGHT
  );
}

function estimateEmbedsHeight(embeds: ChatMessage["embeds"]): number {
  if (!embeds?.length) return 0;

  const tables = embeds.filter((embed) => embed.type === "table");
  const figures = embeds.filter((embed) => embed.type !== "table");

  let height = 16;
  height += tables.length * EMBED_TABLE_HEIGHT;

  if (figures.length === 1) {
    height += EMBED_FIGURE_HEIGHT;
  } else if (figures.length > 1) {
    height += EMBED_GALLERY_HEIGHT;
  }

  return height;
}

export function estimateMessageHeight(message: ChatMessage): number {
  let height = MESSAGE_CHROME + estimateTextHeight(message.content);

  if (message.role === "assistant") {
    height += estimateAgentStepsHeight(message);
    height += estimateEmbedsHeight(message.embeds);
    if (message.streaming) {
      height += STREAMING_CURSOR_HEIGHT;
    }
  }

  return Math.max(height, 96);
}
