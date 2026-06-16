import { lazy, memo, Suspense } from "react";
import {
  citationKey,
  citationToViewerTarget,
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

            {section.citations.length > 0 ? (
              <div className="section-citations">
                {section.citations.map((citation, index) => {
                  const pageHint = citation.page
                    ? t("viewer.pageHint", { page: citation.page })
                    : "";
                  const nameLabel = formatCitationBadgeName(
                    citation,
                    citations,
                  );
                  const indexLabel = formatCitationBadgeIndex(
                    citation,
                    citations,
                  );

                  return (
                    <button
                      key={`${citationKey(citation)}-${index}`}
                      type="button"
                      className="citation-badge"
                      title={`${citation.document_name}${pageHint}${
                        citation.section ? ` · ${citation.section}` : ""
                      }\n${citation.snippet}`}
                      onClick={() =>
                        onOpenDocument(citationToViewerTarget(citation))
                      }
                    >
                      <PdfBadgeIcon />
                      <span className="citation-badge-name">{nameLabel}</span>
                      {indexLabel ? (
                        <span className="citation-badge-index">
                          {indexLabel}
                        </span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>
        );
      })}
    </>
  );
}

export default memo(MessageContent);
