import { memo, useMemo, useState } from "react";
import ImageLightbox from "./ImageLightbox";
import {
  embedDedupeKey,
  embedToViewerTarget,
  isOrphanInlineSuffix,
  isTrailingPunctuationOnly,
  proseSegmentsHaveContent,
  segmentsDisplayText,
  segmentsToMarkdownSource,
  splitMessageWithCitations,
  type MessageSegment,
  type ViewerTarget,
} from "./citations";
import { useI18n } from "./i18n";
import ProseBlock from "./ProseBlock";
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

type SectionBlock =
  | { kind: "prose"; segments: MessageSegment[] }
  | { kind: "embeds"; embeds: MessageEmbed[] };

function buildSectionBlocks(segments: MessageSegment[]): SectionBlock[] {
  const blocks: SectionBlock[] = [];
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

  while (blocks.length >= 2) {
    const trailing = blocks[blocks.length - 1];
    const beforeTrailing = blocks[blocks.length - 2];
    if (
      trailing.kind !== "prose" ||
      beforeTrailing.kind !== "embeds" ||
      blocks.length < 3
    ) {
      break;
    }

    const trailingText = segmentsDisplayText(trailing.segments);
    if (
      !isTrailingPunctuationOnly(trailingText) &&
      !isOrphanInlineSuffix(trailing.segments)
    ) {
      break;
    }

    const anchor = blocks[blocks.length - 3];
    if (anchor.kind !== "prose") {
      break;
    }

    blocks[blocks.length - 3] = {
      kind: "prose",
      segments: [...anchor.segments, ...trailing.segments],
    };
    blocks.pop();
  }

  return blocks;
}

function embedDisplayCaption(
  embed: MessageEmbed,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  const prefix = `[${embed.ref}]`;
  const body =
    embed.caption?.trim() ||
    (embed.document_name
      ? `${embed.document_name} ${t("viewer.pageHint", { page: embed.page })}`
      : undefined);
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
          title={linkLabel}
          onClick={() => onOpenDocument(embedToViewerTarget(embed))}
        >
          {linkLabel}
        </button>
      </figcaption>
    </figure>
  );
}

interface SectionViewProps {
  blocks: SectionBlock[];
  citations: Citation[];
  onOpenDocument: (target: ViewerTarget) => void;
}

const SectionView = memo(function SectionView({
  blocks,
  citations,
  onOpenDocument,
}: SectionViewProps) {
  if (!blocks.length) {
    return null;
  }

  return (
    <div className="answer-section-flow">
      {blocks.map((block, index) => {
        if (block.kind === "prose") {
          if (!proseSegmentsHaveContent(block.segments)) return null;
          const mdSource = segmentsToMarkdownSource(block.segments);
          return (
            <div key={`prose-${index}`} className="answer-prose">
              <ProseBlock
                content={mdSource}
                citations={citations}
                onOpenDocument={onOpenDocument}
              />
            </div>
          );
        }

        const isTable = block.embeds.some((embed) => embed.type === "table");
        const compact = block.embeds.length === 1 && !isTable;
        const isGallery = block.embeds.length > 1 && !isTable;

        return (
          <div
            key={`embeds-${index}`}
            className={`answer-media-figures${
              isTable ? " answer-media-block--table" : ""
            }${compact ? " answer-media-block--compact" : ""}${
              isGallery ? " answer-media-figures--row" : ""
            }`}
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
});

function MessageContent({
  content,
  citations = [],
  embeds = [],
  streaming = false,
  onOpenDocument,
}: MessageContentProps) {
  const segments = useMemo(
    () =>
      content.trim()
        ? splitMessageWithCitations(content, citations, {
            hideUnmatched: true,
            embeds,
            streaming,
          })
        : [],
    [content, citations, embeds, streaming],
  );

  const blocks = useMemo(() => buildSectionBlocks(segments), [segments]);

  if (!segments.length) return null;

  return (
    <div className="message-section-body">
      <SectionView
        blocks={blocks}
        citations={citations}
        onOpenDocument={onOpenDocument}
      />
    </div>
  );
}

export default memo(MessageContent);
