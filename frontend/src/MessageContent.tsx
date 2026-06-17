import { memo, useState } from "react";
import ImageLightbox from "./ImageLightbox";
import {
  embedDedupeKey,
  isCompactMediaText,
  segmentsToRenderableContent,
  splitContentIntoSections,
  splitMessageWithCitations,
  type MessageSegment,
} from "./citations";
import type { ViewerTarget } from "./citations";
import { useI18n } from "./i18n";
import MarkdownText from "./MarkdownText";
import type { Citation, MessageEmbed } from "./types";

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
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const caption = embedDisplayCaption(embed, t);
  const linkLabel =
    caption ?? t("viewer.pageHint", { page: embed.page }).trim();
  const isTable = embed.type === "table";

  return (
    <figure
      className={`answer-embed${
        isTable ? " answer-embed--table" : " answer-embed--figure"
      }`}
    >
      <button
        type="button"
        className="answer-embed-image-btn"
        aria-label={t("viewer.viewEnlarged")}
        onClick={() => setLightboxOpen(true)}
      >
        <img
          src={embed.url}
          alt={linkLabel}
          loading="lazy"
          className="answer-embed-image"
        />
      </button>
      <ImageLightbox
        open={lightboxOpen}
        src={embed.url}
        alt={linkLabel}
        caption={caption}
        onClose={() => setLightboxOpen(false)}
      />
      <figcaption>
        <button
          type="button"
          className="answer-embed-link"
          onClick={() =>
            onOpenDocument({
              documentId: embed.document_id,
              documentName: embed.document_name ?? "",
              page: embed.page,
              section: embed.caption ?? null,
              bbox: embed.bbox ?? null,
            })
          }
        >
          {linkLabel}
        </button>
      </figcaption>
    </figure>
  );
}

interface SectionViewProps {
  segments: MessageSegment[];
  citations: Citation[];
  onOpenDocument: (target: ViewerTarget) => void;
}

function SectionView({
  segments,
  citations,
  onOpenDocument,
}: SectionViewProps) {
  const proseContent = segmentsToRenderableContent(segments);
  const sectionEmbeds = segments
    .filter(
      (segment): segment is Extract<MessageSegment, { type: "embed" }> =>
        segment.type === "embed",
    )
    .map((segment) => segment.embed);
  const hasInlineRefs = segments.some(
    (segment) => segment.type === "citation" || segment.type === "embed",
  );

  if (!proseContent.trim() && sectionEmbeds.length === 0) {
    return null;
  }

  const markdown = proseContent.trim() ? (
    <MarkdownText
      content={proseContent}
      inline={hasInlineRefs}
      citations={citations}
      onOpenDocument={onOpenDocument}
    />
  ) : null;

  if (sectionEmbeds.length === 0) {
    return <div className="answer-prose">{markdown}</div>;
  }

  const isTable = sectionEmbeds.some((embed) => embed.type === "table");
  const compact =
    isCompactMediaText(
      segments.filter((segment) => segment.type !== "embed"),
    ) && !isTable;

  return (
    <div
      className={`answer-media-block${
        isTable ? " answer-media-block--table" : ""
      }${compact ? " answer-media-block--compact" : ""}`}
    >
      {markdown ? <div className="answer-media-text">{markdown}</div> : null}
      <div className="answer-media-figures">
        {sectionEmbeds.map((embed) => (
          <AnswerEmbedFigure
            key={embedDedupeKey(embed)}
            embed={embed}
            onOpenDocument={onOpenDocument}
          />
        ))}
      </div>
    </div>
  );
}

function MessageContent({
  content,
  citations = [],
  embeds = [],
  onOpenDocument,
}: MessageContentProps) {
  if (!content.trim()) return null;

  const sections = splitContentIntoSections(content);
  const seenEmbedKeys = new Set<string>();

  return (
    <>
      {sections.map((sectionText, sectionIndex) => {
        const segments = splitMessageWithCitations(sectionText, citations, {
          hideUnmatched: true,
          embeds,
        }).filter((segment) => {
          if (segment.type !== "embed") return true;
          const embedKey = embedDedupeKey(segment.embed);
          if (seenEmbedKeys.has(embedKey)) return false;
          seenEmbedKeys.add(embedKey);
          return true;
        });

        return (
          <div key={sectionIndex} className="message-section">
            <div className="message-section-body">
              <SectionView
                segments={segments}
                citations={citations}
                onOpenDocument={onOpenDocument}
              />
            </div>
          </div>
        );
      })}
    </>
  );
}

export default memo(MessageContent);
