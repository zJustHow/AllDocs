import { memo, useCallback, useLayoutEffect, useMemo, useRef } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { renderToStaticMarkup } from "react-dom/server";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { hasCitationPlaceholders } from "./citationPlaceholders";
import {
  citationToViewerTarget,
  formatCitationLabel,
  formatCitationTooltip,
  type ViewerTarget,
} from "./citations";
import { useI18n } from "./i18n";
import {
  getCachedMarkdownHtml,
  setCachedMarkdownHtml,
  type MarkdownCacheKind,
} from "./markdownCache";
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

function readCitationIndex(
  node: unknown,
  props: Record<string, unknown>,
): number | null {
  const nodeProps = (node as { properties?: Record<string, unknown> } | undefined)
    ?.properties;
  const dataIndex =
    props.dataIndex ??
    props["data-index"] ??
    nodeProps?.dataIndex ??
    nodeProps?.["data-index"];
  const index = Number(dataIndex);
  return Number.isFinite(index) ? index : null;
}

const staticCitationComponents: Components = {
  p: inlineParagraph,
  cite: ({ node, ...props }) => {
    const index = readCitationIndex(node, props);
    if (index === null) return null;

    return (
      <button
        type="button"
        className="citation-link"
        data-citation-index={index}
      >
        {formatCitationLabel(index)}
      </button>
    );
  },
};

function renderCachedMarkdownHtml(
  content: string,
  kind: MarkdownCacheKind,
): string {
  const cached = getCachedMarkdownHtml(content, kind);
  if (cached) return cached;

  const withCitations = kind === "citations";
  const html = renderToStaticMarkup(
    <ReactMarkdown
      remarkPlugins={withCitations ? citationRemarkPlugins : remarkPlugins}
      components={withCitations ? staticCitationComponents : undefined}
      urlTransform={(url) => url}
    >
      {content}
    </ReactMarkdown>,
  );
  return setCachedMarkdownHtml(content, kind, html);
}

function ProseBlock({ content, citations, onOpenDocument }: ProseBlockProps) {
  const { t } = useI18n();
  const withCitations = hasCitationPlaceholders(content);
  const containerRef = useRef<HTMLDivElement>(null);

  const html = useMemo(() => {
    if (!content.trim()) return "";
    return renderCachedMarkdownHtml(
      content,
      withCitations ? "citations" : "block",
    );
  }, [content, withCitations]);

  useLayoutEffect(() => {
    if (!withCitations || !containerRef.current) return;

    for (const button of containerRef.current.querySelectorAll<HTMLButtonElement>(
      "[data-citation-index]",
    )) {
      const index = Number(button.dataset.citationIndex);
      const citation = citations[index];
      if (!citation) continue;

      const pageHint = citation.page
        ? t("viewer.pageHint", { page: citation.page })
        : "";
      button.title = formatCitationTooltip(citation, pageHint);
    }
  }, [citations, html, t, withCitations]);

  const handleClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const target = (event.target as HTMLElement | null)?.closest(
        "[data-citation-index]",
      );
      if (!(target instanceof HTMLButtonElement)) return;

      const index = Number(target.dataset.citationIndex);
      const citation = citations[index];
      if (!citation) return;

      onOpenDocument(citationToViewerTarget(citation));
    },
    [citations, onOpenDocument],
  );

  if (!html) {
    return null;
  }

  return (
    <div
      ref={containerRef}
      className="markdown-preview"
      dangerouslySetInnerHTML={{ __html: html }}
      onClick={withCitations ? handleClick : undefined}
    />
  );
}

export default memo(ProseBlock);
