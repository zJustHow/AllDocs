import { describe, expect, it } from "vitest";
import { estimateMessageHeight } from "./messageEstimateSize";
import type { ChatMessage } from "./types";

function assistantMessage(partial: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "a1",
    role: "assistant",
    content: "Short answer.",
    ...partial,
  };
}

describe("estimateMessageHeight", () => {
  it("estimates taller heights for long markdown content", () => {
    const short = estimateMessageHeight(assistantMessage({ content: "Hi" }));
    const long = estimateMessageHeight(
      assistantMessage({
        content: "A".repeat(200),
      }),
    );

    expect(long).toBeGreaterThan(short);
  });

  it("adds agent step and streaming chrome for assistant messages", () => {
    const idle = estimateMessageHeight(assistantMessage());
    const running = estimateMessageHeight(
      assistantMessage({
        agentRunning: true,
        agentSteps: [
          {
            step: 1,
            thought: "Searching",
            action: "search",
            action_input: {},
            observation: "",
            status: "running",
          },
        ],
        streaming: true,
      }),
    );

    expect(running).toBeGreaterThan(idle);
  });

  it("adds embed height for tables and figures", () => {
    const withTable = estimateMessageHeight(
      assistantMessage({
        embeds: [
          {
            ref: 1,
            document_id: "doc-1",
            page: 1,
            type: "table",
            url: "/table.png",
            regions: [],
          },
        ],
      }),
    );
    const withFigures = estimateMessageHeight(
      assistantMessage({
        embeds: [
          {
            ref: 1,
            document_id: "doc-1",
            page: 1,
            type: "figure",
            url: "/a.png",
            regions: [],
          },
          {
            ref: 2,
            document_id: "doc-1",
            page: 2,
            type: "figure",
            url: "/b.png",
            regions: [],
          },
        ],
      }),
    );

    expect(withTable).toBeGreaterThan(estimateMessageHeight(assistantMessage()));
    expect(withFigures).toBeGreaterThan(estimateMessageHeight(assistantMessage()));
    expect(withTable).toBeGreaterThan(withFigures);
  });

  it("enforces a minimum row height", () => {
    expect(estimateMessageHeight({ id: "u1", role: "user", content: "" })).toBeGreaterThanOrEqual(
      96,
    );
  });
});
