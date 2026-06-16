import { memo, useEffect, useState } from "react";
import { useI18n } from "./i18n";
import type { AgentStepEvent } from "./types";

interface AgentStepsProps {
  steps: AgentStepEvent[];
  running?: boolean;
}

function summarizeActionInput(action: string, input: Record<string, unknown>): string[] {
  if (action === "search_chunks" && typeof input.query === "string") {
    return [input.query];
  }
  if (action === "search_chunks_batch" && Array.isArray(input.searches)) {
    return input.searches
      .map((search) => {
        if (typeof search === "object" && search && "query" in search) {
          return String((search as { query: unknown }).query ?? "");
        }
        return "";
      })
      .filter(Boolean);
  }
  if (action === "lookup_toc" && typeof input.question === "string") {
    return [input.question];
  }
  if (action === "read_chunks" && Array.isArray(input.chunk_ids)) {
    return [`${input.chunk_ids.length} chunk(s)`];
  }
  if (action === "finish" && typeof input.reason === "string") {
    return [input.reason];
  }
  return [];
}

function truncate(text: string, max = 160): string {
  const trimmed = text.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max)}…`;
}

function AgentSteps({ steps, running = false }: AgentStepsProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(running);

  useEffect(() => {
    if (running) setExpanded(true);
  }, [running]);

  useEffect(() => {
    if (!running && steps.length > 0) setExpanded(false);
  }, [running, steps.length]);

  const toolLabel = (action: string) => {
    const key = `agent.tools.${action}`;
    const label = t(key);
    return label === key ? action : label;
  };

  const visibleSteps = steps.filter((step) => step.action !== "planning" || step.status === "running");
  const latestRunning = [...steps].reverse().find((step) => step.status === "running");

  const summary =
    steps.length === 0
      ? t("agent.planning")
      : running && latestRunning
        ? t("agent.executing", { action: toolLabel(latestRunning.action) })
        : t("agent.summary", {
            count: steps.filter((step) => step.status !== "running").length,
            actions: steps
              .filter((step) => step.action !== "planning" && step.status !== "running")
              .map((step) => toolLabel(step.action))
              .join(" → "),
          });

  if (steps.length === 0 && !running) return null;

  return (
    <details
      className={`agent-steps ${running ? "is-running" : ""}`}
      open={expanded}
      onToggle={(event) => setExpanded((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="agent-steps-summary">
        <span className="agent-steps-dot" aria-hidden="true" />
        <span>{summary}</span>
      </summary>

      <div className="agent-steps-body">
        {visibleSteps.map((step) => {
          const inputLines = summarizeActionInput(step.action, step.action_input);
          const isRunning = step.status === "running";
          return (
            <article
              key={step.step}
              className={`agent-step ${isRunning ? "is-running" : ""}`}
            >
              <div className="agent-step-head">
                <span className="agent-step-num">{step.step}</span>
                <span className={`agent-tool-badge tool-${step.action}`}>
                  {toolLabel(step.action)}
                </span>
                {isRunning ? (
                  <span className="agent-step-status">{t("agent.inProgress")}</span>
                ) : null}
                {!isRunning && step.evidence_count != null ? (
                  <span className="agent-evidence-count">
                    {t("agent.evidenceCount", { count: step.evidence_count })}
                  </span>
                ) : null}
              </div>
              {step.thought ? <p className="agent-thought">{step.thought}</p> : null}
              {inputLines.length > 0 ? (
                <ul className="agent-action-input-list">
                  {inputLines.map((line, index) => (
                    <li key={`${step.step}-${index}`} className="agent-action-input">
                      {line}
                    </li>
                  ))}
                </ul>
              ) : null}
              {!isRunning && step.observation ? (
                <pre className="agent-observation" title={step.observation}>
                  {truncate(step.observation, 240)}
                </pre>
              ) : null}
            </article>
          );
        })}

        {running && steps.length === 0 ? (
          <p className="agent-steps-wait">{t("agent.planning")}</p>
        ) : null}
      </div>
    </details>
  );
}

export default memo(AgentSteps);
