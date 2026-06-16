import { lazy, memo, Suspense, useCallback, useState } from "react";
import {
  citationKey,
  citationToViewerTarget,
  embedDedupeKey,
  formatCitationBadgeIndex,
  formatCitationBadgeName,
  groupContentIntoSections,
  splitMessageWithCitations,
  stripInlineCitationMarkers,
} from "./citations";
import type { ViewerTarget } from "./citations";
import { useI18n } from "./i18n";
import { PdfBadgeIcon } from "./icons";
import type { Citation, MessageEmbed } from "./types";

const MarkdownText = lazy(() => import("./MarkdownText"));

function citationTooltip(
  citation: Citation,
  pageHint: string,
): string {
  return `${citation.document_name}${pageHint}${
    citation.section ? ` · ${citation.section}` : ""
  }\n${citation.snippet}`;
}

function pageHintFor(citation: Citation, t: (key: string, vars?: Record<string, unknown>) => string): string {
  return citation.page ? t("viewer.pageHint", { page: citation.page }) : "";
}

interface SectionCitationsProps {
  sectionCitations: Citation[];
  allCitations: Citation[];
  onOpenDocument: (target: ViewerTarget) => void;
}

function SectionCitations({
  sectionCitations,
  allCitations,
  onOpenDocument,
}: SectionCitationsProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);

  const toggleExpanded = useCallback(() => {
    setExpanded((value) => !value);
  }, []);

  if (sectionCitations.length === 0) return null;

  if (sectionCitations.length === 1) {
    const citation = sectionCitations[0];
    const indexLabel = formatCitationBadgeIndex(citation, allCitations);

    return (
      <div className="section-citations">
        <button
          type="button"
          className="citation-badge"
          title={citationTooltip(citation, pageHintFor(citation, t))}
          onClick={() => onOpenDocument(citationToViewerTarget(citation))}
        >
          <PdfBadgeIcon />
          <span className="citation-badge-name">
            {formatCitationBadgeName(citation, allCitations)}
          </span>
          {indexLabel ? (
            <span className="citation-badge-index">{indexLabel}</span>
          ) : null}
        </button>
      </div>
    );
  }

  if (!expanded) {
    return (
      <div className="section-citations">
        <button
          type="button"
          className="citation-badge citation-badge-more"
          aria-label={t("citation.showAll", { count: sectionCitations.length })}
          aria-expanded={false}
          onClick={toggleExpanded}
        >
          …
        </button>
      </div>
    );
  }

  return (
    <div className="section-citations">
      {sectionCitations.map((citation, index) => {
        const indexLabel = formatCitationBadgeIndex(citation, allCitations);
        return (
          <button
            key={`${citationKey(citation)}-${index}`}
            type="button"
            className="citation-badge"
            title={citationTooltip(citation, pageHintFor(citation, t))}
            onClick={() => onOpenDocument(citationToViewerTarget(citation))}
          >
            <PdfBadgeIcon />
            <span className="citation-badge-name">
              {formatCitationBadgeName(citation, allCitations)}
            </span>
            {indexLabel ? (
              <span className="citation-badge-index">{indexLabel}</span>
            ) : null}
          </button>
        );
      })}
      <button
        type="button"
        className="citation-badge citation-badge-more"
        aria-label={t("citation.collapse")}
        aria-expanded
        onClick={toggleExpanded}
      >
        …
      </button>
    </div>
  );
}

interface MessageContentProps {
  content: string;
  citations?: Citation[];
  embeds?: MessageEmbed[];
  streaming?: boolean;
  onOpenDocument: (target: ViewerTarget) => void;
}

function MessageContent({
  content,
  citations = [],
  embeds = [],
  streaming = false,
  onOpenDocument,
}: MessageContentProps) {
  const { t } = useI18n();

  if (streaming) {
    const plain = stripInlineCitationMarkers(content);
    if (!plain.trim()) return null;
    return <div className="streaming-text">{plain}</div>;
  }

  const sections = groupContentIntoSections(content, citations, embeds);
  const seenEmbedKeys = new Set<string>();

  return (
    <>
      {sections.map((section, sectionIndex) => {
        const segments = splitMessageWithCitations(section.content, citations, {
          hideUnmatched: true,
          embeds,
        });
        const hasEmbeds = segments.some((segment) => segment.type === "embed");

        return (
          <div key={sectionIndex} className="message-section">
            {segments.map((segment, index) => {
              if (segment.type === "text") {
                return (
                  <Suspense
                    key={index}
                    fallback={
                      <div className="streaming-text">{segment.value}</div>
                    }
                  >
                    <MarkdownText
                      content={segment.value}
                      inline={hasEmbeds}
                    />
                  </Suspense>
                );
              }

              if (segment.type !== "embed") {
                return null;
              }

              const embedKey = embedDedupeKey(segment.embed);
              if (seenEmbedKeys.has(embedKey)) {
                return null;
              }
              seenEmbedKeys.add(embedKey);

              const caption =
                segment.embed.caption ??
                (segment.embed.document_name
                  ? `${segment.embed.document_name} p.${segment.embed.page}`
                  : undefined);
              return (
                <figure key={index} className="answer-embed">
                  <img
                    src={segment.embed.url}
                    alt={
                      caption ??
                      t("viewer.pageHint", { page: segment.embed.page })
                    }
                    loading="lazy"
                    className="answer-embed-image"
                  />
                  {caption ? <figcaption>{caption}</figcaption> : null}
                  <button
                    type="button"
                    className="answer-embed-link"
                    onClick={() =>
                      onOpenDocument({
                        documentId: segment.embed.document_id,
                        documentName: segment.embed.document_name ?? "",
                        page: segment.embed.page,
                        section: segment.embed.caption ?? null,
                      })
                    }
                  >
                    {t("viewer.openSource")}
                  </button>
                </figure>
              );
            })}

            <SectionCitations
              sectionCitations={section.citations}
              allCitations={citations}
              onOpenDocument={onOpenDocument}
            />
          </div>
        );
      })}
    </>
  );
}

export default memo(MessageContent);
