import { lazy, memo, Suspense } from "react";
import {
  citationToViewerTarget,
  embedDedupeKey,
  formatCitationLabel,
  getCitationIndex,
  splitContentIntoSections,
  splitMessageWithCitations,
  stripInlineCitationMarkers,
} from "./citations";
import type { ViewerTarget } from "./citations";
import { useI18n } from "./i18n";
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

interface InlineCitationLinkProps {
  citation: Citation;
  allCitations: Citation[];
  onOpenDocument: (target: ViewerTarget) => void;
}

function InlineCitationLink({
  citation,
  allCitations,
  onOpenDocument,
}: InlineCitationLinkProps) {
  const { t } = useI18n();
  const index = getCitationIndex(citation, allCitations);
  if (index < 0) return null;

  return (
    <button
      type="button"
      className="citation-link"
      title={citationTooltip(citation, pageHintFor(citation, t))}
      onClick={() => onOpenDocument(citationToViewerTarget(citation))}
    >
      {formatCitationLabel(index)}
    </button>
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
  if (streaming) {
    const plain = stripInlineCitationMarkers(content);
    if (!plain.trim()) return null;
    return <div className="streaming-text">{plain}</div>;
  }

  const sections = splitContentIntoSections(content);
  const seenEmbedKeys = new Set<string>();

  return (
    <>
      {sections.map((sectionText, sectionIndex) => {
        const segments = splitMessageWithCitations(sectionText, citations, {
          hideUnmatched: true,
          embeds,
        });
        const hasInlineRefs = segments.some(
          (segment) => segment.type === "citation" || segment.type === "embed",
        );

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
                      <MarkdownText
                        content={segment.value}
                        inline={hasInlineRefs}
                      />
                    </Suspense>
                  );
                }

                if (segment.type === "citation") {
                  return (
                    <InlineCitationLink
                      key={index}
                      citation={segment.citation}
                      allCitations={citations}
                      onOpenDocument={onOpenDocument}
                    />
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
          </div>
        );
      })}
    </>
  );
}

export default memo(MessageContent);
