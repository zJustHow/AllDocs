import { memo, useMemo } from "react";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import { renderToStaticMarkup } from "react-dom/server";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import CitationLink from "./CitationLink";
import { hasCitationPlaceholders } from "./citationPlaceholders";
import type { ViewerTarget } from "./citations";
import { getCachedMarkdownHtml, setCachedMarkdownHtml } from "./markdownCache";
import { remarkCitationPlaceholders } from "./remarkCitationPlaceholders";
import type { Citation } from "./types";

interface ProseBlockProps {
  content: string;
  citations: Citation[];
  onOpenDocument: (target: ViewerTarget) => void;
}

// Single-tilde strikethrough (~text~) breaks numeric ranges like 1~255 / 1~8.
const remarkPlugins = [
  [remarkGfm, { singleTilde: false }],
  remarkBreaks,
] as const;

const citationRemarkPlugins = [
  ...remarkPlugins,
  remarkCitationPlaceholders,
] as const;

const inlineParagraph: Components["p"] = ({ children }) => (
  <span className="md-inline">{children}</span>
);

function renderCachedMarkdownHtml(content: string, inline: boolean): string {
  const cached = getCachedMarkdownHtml(content, inline);
  if (cached) return cached;

  const html = renderToStaticMarkup(
    <ReactMarkdown
      remarkPlugins={remarkPlugins}
      components={inline ? { p: inlineParagraph } : undefined}
      urlTransform={(url) => url}
    >
      {content}
    </ReactMarkdown>,
  );
  return setCachedMarkdownHtml(content, inline, html);
}

function ProseBlock({ content, citations, onOpenDocument }: ProseBlockProps) {
  const withCitations = hasCitationPlaceholders(content);

  const components = useMemo((): Components => {
    if (!withCitations) return {};

    const cite: Components["cite"] = ({ node, ...props }) => {
      const rawProps = props as {
        dataIndex?: number | string;
        "data-index"?: number | string;
      };
      const dataIndex =
        rawProps.dataIndex ??
        rawProps["data-index"] ??
        (node?.properties?.dataIndex as number | string | undefined) ??
        (node?.properties?.["data-index"] as number | string | undefined);
      const index = Number(dataIndex);
      if (!Number.isFinite(index)) return null;

      const citation = citations[index];
      if (!citation) return null;

      return (
        <CitationLink
          citation={citation}
          index={index}
          onOpenDocument={onOpenDocument}
        />
      );
    };

    return { p: inlineParagraph, cite };
  }, [citations, onOpenDocument, withCitations]);

  if (!content.trim()) {
    return null;
  }

  if (!withCitations) {
    const html = renderCachedMarkdownHtml(content, false);
    return (
      <div
        className="markdown-preview"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  }

  return (
    <div className="markdown-preview">
      <ReactMarkdown
        remarkPlugins={citationRemarkPlugins}
        components={components}
        urlTransform={(url) => url}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default memo(ProseBlock);
