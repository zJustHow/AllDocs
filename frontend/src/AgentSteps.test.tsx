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
          action: "read_chunks",
          action_input: { chunk_ids: ["abc123"] },
          observation: "",
          status: "running",
        },
      ],
      true,
    );

    expect(screen.getByText(/Read chunks in progress/i)).toBeInTheDocument();
  });
});
