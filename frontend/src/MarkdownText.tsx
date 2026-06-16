import { memo, useMemo } from "react";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import { renderToStaticMarkup } from "react-dom/server";
import remarkGfm from "remark-gfm";
import {
  getCachedMarkdownHtml,
  setCachedMarkdownHtml,
} from "./markdownCache";

interface MarkdownTextProps {
  content: string;
  /** Use span instead of p for paragraph nodes so text can flow inline with citation badges. */
  inline?: boolean;
}

const remarkPlugins = [remarkGfm];

const inlineComponents: Components = {
  p: ({ children }) => <span className="md-inline">{children}</span>,
};

function renderMarkdownHtml(content: string, inline: boolean): string {
  const cached = getCachedMarkdownHtml(content, inline);
  if (cached) return cached;

  const html = renderToStaticMarkup(
    <ReactMarkdown
      remarkPlugins={remarkPlugins}
      components={inline ? inlineComponents : undefined}
      urlTransform={(url) => url}
    >
      {content}
    </ReactMarkdown>,
  );
  return setCachedMarkdownHtml(content, inline, html);
}

function MarkdownText({ content, inline = false }: MarkdownTextProps) {
  if (!content.trim()) {
    return null;
  }

  const html = useMemo(
    () => renderMarkdownHtml(content, inline),
    [content, inline],
  );

  return (
    <div
      className="markdown-preview"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export default memo(MarkdownText);
