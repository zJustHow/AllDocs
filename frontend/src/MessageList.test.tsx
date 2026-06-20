/** @vitest-environment jsdom */
import { useRef } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import MessageList from "./MessageList";
import { I18nProvider } from "./i18n";
import type { ChatMessage } from "./types";

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 180,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        start: index * 180,
        key: String(index),
      })),
    measureElement: vi.fn(),
    scrollToIndex: vi.fn(),
  }),
}));

const messages: ChatMessage[] = [
  { id: "u1", role: "user", content: "Question one" },
  {
    id: "a1",
    role: "assistant",
    content: "Answer one with [1].",
    citations: [
      {
        document_id: "doc-1",
        document_name: "Manual",
        page: 1,
        section: null,
        snippet: "Step",
        regions: [],
      },
    ],
  },
];

function MessageListHarness() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const spacerRef = useRef<HTMLDivElement>(null);

  return (
    <div ref={scrollRef} style={{ height: 600, overflow: "auto" }}>
      <MessageList
        messages={messages}
        scrollRef={scrollRef}
        scrollTargetId={null}
        onOpenDocument={vi.fn()}
        registerRef={vi.fn()}
        spacerRef={spacerRef}
      />
    </div>
  );
}

describe("MessageList", () => {
  it("renders virtualized chat rows", () => {
    render(
      <I18nProvider>
        <MessageListHarness />
      </I18nProvider>,
    );

    expect(screen.getByText("Question one")).toBeInTheDocument();
    expect(screen.getByText(/Answer one/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "[1]" })).toBeInTheDocument();
    expect(document.querySelector(".messages-virtual-row")).toBeInTheDocument();
  });
});
