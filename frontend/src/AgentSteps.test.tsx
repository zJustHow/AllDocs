/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import AgentSteps from "./AgentSteps";
import { I18nProvider } from "./i18n";
import type { AgentStepEvent } from "./types";

const searchStep: AgentStepEvent = {
  step: 1,
  thought: "Looking for motor calibration steps.",
  reasoning: "Need setup section first.",
  action: "search_chunks",
  action_input: { query: "motor calibration" },
  observation: "Found 3 matching chunks.",
  evidence_count: 3,
  status: "done",
};

function renderSteps(steps: AgentStepEvent[], running = false) {
  render(
    <I18nProvider>
      <AgentSteps steps={steps} running={running} />
    </I18nProvider>,
  );
}

describe("AgentSteps", () => {
  it("returns null when there are no steps and agent is idle", () => {
    render(
      <I18nProvider>
        <AgentSteps steps={[]} running={false} />
      </I18nProvider>,
    );

    expect(document.querySelector(".agent-steps")).not.toBeInTheDocument();
  });

  it("shows planning summary while running without steps", () => {
    renderSteps([], true);

    const summary = document.querySelector(".agent-steps-summary span:last-child");
    expect(summary?.textContent).toMatch(/Planning retrieval|规划检索/);
  });

  it("renders action input lines and observation for completed steps", async () => {
    const user = userEvent.setup();
    renderSteps([searchStep]);

    await user.click(document.querySelector(".agent-steps-summary")!);

    expect(screen.getByText("motor calibration")).toBeInTheDocument();
    expect(screen.getByText(/Found 3 matching chunks/i)).toBeInTheDocument();
    expect(screen.getByText(/3 source/i)).toBeInTheDocument();
  });

  it("shows executing label for the latest running step", () => {
    renderSteps(
      [
        searchStep,
        {
          step: 2,
          thought: "",
          action: "read_neighbor_chunks",
          action_input: { chunk_id: "11111111-1111-1111-1111-111111111111", before: 1, after: 1 },
          observation: "",
          status: "running",
        },
      ],
      true,
    );

    expect(screen.getByText(/Neighbor chunks in progress|正在相邻片段/i)).toBeInTheDocument();
  });

  it("translates parallel tool names joined with +", () => {
    renderSteps(
      [
        {
          step: 2,
          thought: "",
          action: "read_neighbor_chunks + search_chunks",
          action_input: {
            calls: [
              {
                action: "read_neighbor_chunks",
                action_input: { chunk_id: "11111111-1111-1111-1111-111111111111", before: 1, after: 1 },
              },
              { action: "search_chunks", action_input: { query: "arcing time" } },
            ],
          },
          observation: "",
          status: "running",
        },
      ],
      true,
    );

    expect(
      screen.getByText(
        /Neighbor chunks \+ Search in progress|正在相邻片段 \+ 语义检索/i,
      ),
    ).toBeInTheDocument();
  });

  it("renders action inputs for additional tool types", async () => {
    const user = userEvent.setup();
    renderSteps([
      {
        step: 1,
        thought: "",
        action: "search_chunks_batch",
        action_input: { searches: [{ query: "alarm reset" }, { query: "motor torque" }] },
        observation: "Found matches.",
        status: "done",
      },
      {
        step: 2,
        thought: "",
        action: "lookup_toc",
        action_input: { question: "Where is calibration?" },
        observation: "TOC hit.",
        status: "done",
      },
      {
        step: 3,
        thought: "",
        action: "lookup_asset",
        action_input: { kind: "Figure", figure_number: "3-1" },
        observation: "Asset found.",
        status: "done",
      },
      {
        step: 4,
        thought: "",
        action: "read_pages",
        action_input: { page_gte: 2, page_lte: 4 },
        observation: "Pages loaded.",
        status: "done",
      },
      {
        step: 5,
        thought: "",
        action: "read_section",
        action_input: { section: "4.5 Floating menu" },
        observation: "Section loaded.",
        status: "done",
      },
      {
        step: 6,
        thought: "",
        action: "search_keyword",
        action_input: { query: "E-204" },
        observation: "Keyword hit.",
        status: "done",
      },
      {
        step: 7,
        thought: "",
        action: "ask_user",
        action_input: { question: "Which robot model?" },
        observation: "",
        status: "done",
      },
      {
        step: 8,
        thought: "",
        action: "finish",
        action_input: { reason: "Enough evidence gathered." },
        observation: "",
        status: "done",
      },
    ]);

    await user.click(document.querySelector(".agent-steps-summary")!);

    expect(screen.getByText("alarm reset")).toBeInTheDocument();
    expect(screen.getByText("motor torque")).toBeInTheDocument();
    expect(screen.getByText("Where is calibration?")).toBeInTheDocument();
    expect(screen.getByText("Figure 3-1")).toBeInTheDocument();
    expect(screen.getByText("p.2–4")).toBeInTheDocument();
    expect(screen.getByText("4.5 Floating menu")).toBeInTheDocument();
    expect(screen.getByText("E-204")).toBeInTheDocument();
    expect(screen.getByText("Which robot model?")).toBeInTheDocument();
    expect(screen.getByText("Enough evidence gathered.")).toBeInTheDocument();
  });

  it("handles edge cases in action input summarization", async () => {
    const user = userEvent.setup();
    renderSteps([
      {
        step: 1,
        thought: "",
        action: "search_chunks_batch",
        action_input: { searches: [{ query: "valid" }, "invalid", { other: "x" }] },
        observation: "",
        status: "done",
      },
      {
        step: 2,
        thought: "",
        action: "lookup_asset",
        action_input: { figure_number: "2-1" },
        observation: "",
        status: "done",
      },
      {
        step: 3,
        thought: "",
        action: "read_section",
        action_input: { question: "Where is the menu?" },
        observation: "",
        status: "done",
      },
    ]);

    await user.click(document.querySelector(".agent-steps-summary")!);

    expect(screen.getByText("valid")).toBeInTheDocument();
    expect(screen.getByText("2-1")).toBeInTheDocument();
    expect(screen.getByText("Where is the menu?")).toBeInTheDocument();
  });

  it("falls back to question when section text is blank", async () => {
    const user = userEvent.setup();
    renderSteps([
      {
        step: 1,
        thought: "",
        action: "read_section",
        action_input: { section: "   ", question: "Menu location" },
        observation: "",
        status: "done",
      },
    ]);

    await user.click(document.querySelector(".agent-steps-summary")!);
    expect(screen.getByText("Menu location")).toBeInTheDocument();
  });

  it("shows reasoning, preserves full observations, and summarizes completed steps", async () => {
    const user = userEvent.setup();
    const longObservation = "x".repeat(300);
    renderSteps([
      {
        step: 1,
        thought: "Scanning the manual.",
        reasoning: "Start with semantic search.",
        action: "search_chunks",
        action_input: { query: "alarm reset" },
        observation: longObservation,
        status: "done",
      },
      {
        step: 2,
        thought: "",
        action: "read_pages",
        action_input: { page: 7 },
        observation: "Loaded page 7.",
        status: "done",
      },
    ]);

    expect(screen.getByText(/2 step\(s\).*Search → Read pages|2 步.*语义检索 → 阅读页面/i)).toBeInTheDocument();

    await user.click(document.querySelector(".agent-steps-summary")!);

    expect(screen.getByText("Start with semantic search.")).toBeInTheDocument();
    expect(screen.getByText("p.7")).toBeInTheDocument();
    const observation = document.querySelector(".agent-observation");
    expect(observation?.textContent).toBe(longObservation);
  });

  it("collapses after the agent finishes running", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <I18nProvider>
        <AgentSteps
          steps={[
            {
              step: 1,
              thought: "",
              action: "search_chunks",
              action_input: { query: "alarm reset" },
              observation: "",
              status: "running",
            },
          ]}
          running
        />
      </I18nProvider>,
    );

    expect(document.querySelector(".agent-steps[open]")).toBeInTheDocument();

    rerender(
      <I18nProvider>
        <AgentSteps
          steps={[
            {
              step: 1,
              thought: "",
              action: "search_chunks",
              action_input: { query: "alarm reset" },
              observation: "Found chunks.",
              status: "done",
            },
          ]}
          running={false}
        />
      </I18nProvider>,
    );

    expect(document.querySelector(".agent-steps[open]")).not.toBeInTheDocument();
    await user.click(document.querySelector(".agent-steps-summary")!);
    expect(document.querySelector(".agent-steps[open]")).toBeInTheDocument();
  });
});
