/** @vitest-environment jsdom */
import { act, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";
import ChatMessageItem from "./ChatMessageItem";
import { I18nProvider } from "./i18n";
import { appendStreamingContent, initStreamingContent } from "./streamingContent";
import type { ChatMessage } from "./types";

function renderItem(message: ChatMessage) {
  const scrollContainerRef = createRef<HTMLDivElement>();
  const registerRef = vi.fn();

  render(
    <I18nProvider>
      <div ref={scrollContainerRef} style={{ height: 400, overflow: "auto" }}>
        <ChatMessageItem
          message={message}
          onOpenDocument={vi.fn()}
          registerRef={registerRef}
          scrollContainerRef={scrollContainerRef}
        />
      </div>
    </I18nProvider>,
  );

  return { registerRef };
}

describe("ChatMessageItem", () => {
  it("renders user messages as plain text", () => {
    renderItem({
      id: "u1",
      role: "user",
      content: "How do I calibrate the robot?",
    });

    expect(screen.getByText("How do I calibrate the robot?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "[1]" })).not.toBeInTheDocument();
  });

  it("renders assistant messages with citations", () => {
    renderItem({
      id: "a1",
      role: "assistant",
      content: "Follow step [1].",
      citations: [
        {
          document_id: "doc-1",
          document_name: "Manual",
          page: 1,
          section: null,
          snippet: "Calibrate axis zero.",
          regions: [],
        },
      ],
    });

    expect(screen.getByRole("button", { name: "[1]" })).toBeInTheDocument();
  });

  it("shows live streaming content and cursor for streaming assistant messages", () => {
    initStreamingContent("stream-1");
    renderItem({
      id: "stream-1",
      role: "assistant",
      content: "",
      streaming: true,
      agentRunning: false,
    });

    act(() => {
      appendStreamingContent("stream-1", "Typing answer");
    });

    expect(screen.getByText(/Typing answer/)).toBeInTheDocument();
    expect(document.querySelector(".cursor")).toBeInTheDocument();
  });
});
