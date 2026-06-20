import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import {
  segmentsToMarkdownSource,
  splitMessageWithCitations,
} from "./citations";
import type { Citation, MessageEmbed } from "./types";

const citations: Citation[] = [
  {
    document_id: "1",
    document_name: "manual",
    page: 1,
    section: null,
    snippet: "a",
    score: 1,
    regions: [],
  },
  {
    document_id: "1",
    document_name: "manual",
    page: 2,
    section: null,
    snippet: "b",
    score: 1,
    regions: [],
  },
  {
    document_id: "1",
    document_name: "manual",
    page: 3,
    section: null,
    snippet: "c",
    score: 1,
    regions: [],
  },
];

const content = `## 三、启动程序回放

1. 接通伺服电源（回放模式下）：
   - 按下示教器上的【伺服准备】键，指示灯长亮即表示伺服已使能 [1]。
2. 启动执行：
   - 按下示教器上的【启动】键（或通过手持盒【启动输出】信号触发）[3]；
   - 此时状态栏"工作中"和"运动中"指示应激活 [3]。`;

function renderMarkdown(md: string): string {
  return renderToStaticMarkup(
    React.createElement(
      ReactMarkdown,
      {
        remarkPlugins: [[remarkGfm, { singleTilde: false }], remarkBreaks],
      },
      md,
    ),
  );
}

describe("splitMessageWithCitations sentence boundaries", () => {
  it("preserves numbered list spacing in markdown output", () => {
    const splitMd = segmentsToMarkdownSource(
      splitMessageWithCitations(content, citations, { hideUnmatched: true }),
    );

    expect(splitMd).toMatch(/1\. 接通伺服电源/);
    expect(splitMd).not.toMatch(/1\.接通伺服电源/);
  });

  it("renders ordered list items without spurious start attributes", () => {
    const splitMd = segmentsToMarkdownSource(
      splitMessageWithCitations(content, citations, { hideUnmatched: true }),
    );
    const html = renderMarkdown(splitMd);

    expect(html).not.toMatch(/start="2"/);
    expect(html).toMatch(/<ol>\s*<li>接通伺服电源/);
    expect(html).toMatch(/<li>启动执行：/);
  });

  it("places embeds after the cited sentence without breaking list markers", () => {
    const embeds: MessageEmbed[] = [
      {
        ref: 5,
        type: "figure",
        url: "/x.png",
        page: 5,
        document_id: "1",
        document_name: "manual",
        regions: [],
        sentence_index: 1,
      },
    ];

    const withEmbed = segmentsToMarkdownSource(
      splitMessageWithCitations(content, citations, {
        hideUnmatched: true,
        embeds,
      }),
    );

    expect(withEmbed).toMatch(/1\. 接通伺服电源/);
    expect(withEmbed).toMatch(/2\. 启动执行/);
  });
});
