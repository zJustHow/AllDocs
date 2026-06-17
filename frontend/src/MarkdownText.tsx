import { memo, useCallback, useMemo, type MouseEvent } from "react";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import { renderToStaticMarkup } from "react-dom/server";
import remarkGfm from "remark-gfm";
import {
  citationToViewerTarget,
  formatCitationLabel,
  formatCitationSnippetExcerpt,
  injectCitationPlaceholders,
  mergeOrphanCitationParagraphs,
  replaceCitationPlaceholdersWithButtons,
} from "./citations";
import type { ViewerTarget } from "./citations";
import { useI18n } from "./i18n";
import {
  getCachedMarkdownHtml,
  setCachedMarkdownHtml,
} from "./markdownCache";
import type { Citation } from "./types";

interface MarkdownTextProps {
  content: string;
  /** Use span instead of p for paragraph nodes so text can flow inline with citation badges. */
  inline?: boolean;
  citations?: Citation[];
  onOpenDocument?: (target: ViewerTarget) => void;
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

function citationTooltip(
  citation: Citation,
  pageHint: string,
): string {
  return `${citation.document_name}${pageHint}${
    citation.section ? ` · ${citation.section}` : ""
  }\n${formatCitationSnippetExcerpt(citation.snippet)}`;
}

function MarkdownText({
  content,
  inline = false,
  citations = [],
  onOpenDocument,
}: MarkdownTextProps) {
  const { t } = useI18n();

  const html = useMemo(() => {
    const hasCitations = citations.length > 0 && onOpenDocument;
    const markdownSource = hasCitations
      ? injectCitationPlaceholders(content, citations, { hideUnmatched: true })
      : content;

    let rendered = hasCitations
      ? renderMarkdownHtml(markdownSource, inline)
      : renderMarkdownHtml(content, inline);

    if (hasCitations) {
      rendered = replaceCitationPlaceholdersWithButtons(rendered, citations, {
        formatLabel: formatCitationLabel,
        formatTitle: (citation) => {
          const pageHint = citation.page
            ? t("viewer.pageHint", { page: citation.page })
            : "";
          return citationTooltip(citation, pageHint);
        },
      });
      rendered = mergeOrphanCitationParagraphs(rendered);
    }

    return rendered;
  }, [content, inline, citations, onOpenDocument, t]);

  const handleClick = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      if (!onOpenDocument || !citations.length) return;

      const target = (event.target as HTMLElement).closest(
        "[data-citation-index]",
      );
      if (!target) return;

      const index = Number(target.getAttribute("data-citation-index"));
      const citation = citations[index];
      if (citation) {
        onOpenDocument(citationToViewerTarget(citation));
      }
    },
    [citations, onOpenDocument],
  );

  if (!content.trim()) {
    return null;
  }

  return (
    <div
      className="markdown-preview"
      dangerouslySetInnerHTML={{ __html: html }}
      onClick={onOpenDocument ? handleClick : undefined}
    />
  );
}

export default memo(MarkdownText);
