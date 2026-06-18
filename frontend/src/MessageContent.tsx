import { memo, useState } from "react";
import ImageLightbox from "./ImageLightbox";
import {
  embedDedupeKey,
  reassignEmbedsAcrossSections,
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
): string {
  const prefix = `[${embed.ref}]`;
  let body: string | undefined;
  if (embed.caption && !looksLikeImageDescription(embed.caption)) {
    body = embed.caption;
  } else if (embed.document_name) {
    body = `${embed.document_name} ${t("viewer.pageHint", { page: embed.page })}`;
  }
  if (!body) {
    return prefix;
  }
  if (/^\[\d+\]/.test(body.trim())) {
    return body;
  }
  return `${prefix} ${body}`;
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
  const blocks: Array<
    | { kind: "prose"; segments: MessageSegment[] }
    | { kind: "embeds"; embeds: MessageEmbed[] }
  > = [];
  let proseBatch: MessageSegment[] = [];

  const flushProse = () => {
    if (!proseBatch.length) return;
    blocks.push({ kind: "prose", segments: proseBatch });
    proseBatch = [];
  };

  for (const segment of segments) {
    if (segment.type === "embed") {
      flushProse();
      const last = blocks[blocks.length - 1];
      if (last?.kind === "embeds") {
        last.embeds.push(segment.embed);
      } else {
        blocks.push({ kind: "embeds", embeds: [segment.embed] });
      }
      continue;
    }
    proseBatch.push(segment);
  }
  flushProse();

  if (!blocks.length) {
    return null;
  }

  return (
    <div className="answer-section-flow">
      {blocks.map((block, index) => {
        if (block.kind === "prose") {
          const proseContent = segmentsToRenderableContent(block.segments);
          if (!proseContent.trim()) return null;
          const hasInlineRefs = block.segments.some(
            (segment) =>
              segment.type === "citation" || segment.type === "embed",
          );
          return (
            <div key={`prose-${index}`} className="answer-prose">
              <MarkdownText
                content={proseContent}
                inline={hasInlineRefs}
                citations={citations}
                onOpenDocument={onOpenDocument}
              />
            </div>
          );
        }

        const isTable = block.embeds.some((embed) => embed.type === "table");
        const compact = block.embeds.length === 1 && !isTable;

        return (
          <div
            key={`embeds-${index}`}
            className={`answer-media-figures${
              isTable ? " answer-media-block--table" : ""
            }${compact ? " answer-media-block--compact" : ""}`}
          >
            {block.embeds.map((embed) => (
              <AnswerEmbedFigure
                key={embedDedupeKey(embed)}
                embed={embed}
                onOpenDocument={onOpenDocument}
              />
            ))}
          </div>
        );
      })}
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
  const segmentsBySection = sections.map((sectionText) =>
    splitMessageWithCitations(sectionText, citations, {
      hideUnmatched: true,
      embeds,
    }),
  );
  const reassignedSegments = reassignEmbedsAcrossSections(
    sections,
    segmentsBySection,
  );
  const seenEmbedKeys = new Set<string>();

  return (
    <>
      {reassignedSegments.map((segments, sectionIndex) => {
        const filteredSegments = segments.filter((segment) => {
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
                segments={filteredSegments}
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
