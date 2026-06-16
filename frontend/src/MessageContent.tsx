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

interface AnswerEmbedFigureProps {
  embed: MessageEmbed;
  onOpenDocument: (target: ViewerTarget) => void;
}

function looksLikeImageDescription(text: string): boolean {
  const trimmed = text.trim();
  if (trimmed.length > 120) return true;
  return /^(这是|图中|该图|本图|如图所示|照片展示)/.test(trimmed);
}

function embedDisplayCaption(
  embed: MessageEmbed,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string | undefined {
  if (embed.caption && !looksLikeImageDescription(embed.caption)) {
    return embed.caption;
  }
  if (embed.document_name) {
    return `${embed.document_name} ${t("viewer.pageHint", { page: embed.page })}`;
  }
  return undefined;
}

function AnswerEmbedFigure({ embed, onOpenDocument }: AnswerEmbedFigureProps) {
  const { t } = useI18n();
  const caption = embedDisplayCaption(embed, t);
  const isTable = embed.type === "table";

  return (
    <figure
      className={`answer-embed${
        isTable ? " answer-embed--table" : " answer-embed--figure"
      }`}
    >
      <img
        src={embed.url}
        alt={caption ?? t("viewer.pageHint", { page: embed.page })}
        loading="lazy"
        className="answer-embed-image"
      />
      {caption ? <figcaption>{caption}</figcaption> : null}
      <button
        type="button"
        className="answer-embed-link"
        onClick={() =>
          onOpenDocument({
            documentId: embed.document_id,
            documentName: embed.document_name ?? "",
            page: embed.page,
            section: embed.caption ?? null,
          })
        }
      >
        {t("viewer.openSource")}
      </button>
    </figure>
  );
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
        return (
          <div key={sectionIndex} className="message-section">
            <div className="message-section-body">
            {segments.map((segment, index) => {
              if (segment.type === "text") {
                return (
                  <Suspense
                    key={index}
                    fallback={
                      <div className="streaming-text">{segment.value}</div>
                    }
                  >
                    <MarkdownText content={segment.value} />
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

              return (
                <AnswerEmbedFigure
                  key={index}
                  embed={segment.embed}
                  onOpenDocument={onOpenDocument}
                />
              );
            })}
            </div>

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
