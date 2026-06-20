import { memo, useEffect, useMemo, useRef, useState } from "react";
import ImageLightbox from "./ImageLightbox";
import {
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
import { embedDedupeKey } from "./shared/contract";
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
  | { kind: "embeds"; embeds: MessageEmbed[]; layout: "figures-row" | "table-row" };

function isTableEmbed(embed: MessageEmbed): boolean {
  return embed.type === "table";
}

/** Tables each get a row; all figures from one sentence share a single row. */
function expandEmbedRun(embedRun: MessageEmbed[]): SectionBlock[] {
  const blocks: SectionBlock[] = [];
  const figures = embedRun.filter((embed) => !isTableEmbed(embed));
  let figuresRowPlaced = false;

  for (const embed of embedRun) {
    if (isTableEmbed(embed)) {
      blocks.push({ kind: "embeds", embeds: [embed], layout: "table-row" });
      continue;
    }
    if (!figuresRowPlaced) {
      blocks.push({ kind: "embeds", embeds: figures, layout: "figures-row" });
      figuresRowPlaced = true;
    }
  }

  return blocks;
}

function buildSectionBlocks(segments: MessageSegment[]): SectionBlock[] {
  const blocks: SectionBlock[] = [];
  let proseBatch: MessageSegment[] = [];
  let embedRun: MessageEmbed[] = [];

  const flushProse = () => {
    if (!proseBatch.length) return;
    blocks.push({ kind: "prose", segments: proseBatch });
    proseBatch = [];
  };

  const flushEmbeds = () => {
    if (!embedRun.length) return;
    blocks.push(...expandEmbedRun(embedRun));
    embedRun = [];
  };

  for (const segment of segments) {
    if (segment.type === "embed") {
      flushProse();
      embedRun.push(segment.embed);
      continue;
    }
    flushEmbeds();
    proseBatch.push(segment);
  }
  flushProse();
  flushEmbeds();

  while (blocks.length >= 2) {
    const trailing = blocks[blocks.length - 1];
    if (trailing.kind !== "prose") {
      break;
    }

    const trailingText = segmentsDisplayText(trailing.segments);
    if (
      !isTrailingPunctuationOnly(trailingText) &&
      !isOrphanInlineSuffix(trailing.segments)
    ) {
      break;
    }

    let embedEnd = blocks.length - 2;
    while (embedEnd >= 0 && blocks[embedEnd].kind === "embeds") {
      embedEnd -= 1;
    }
    if (embedEnd < 0 || blocks[embedEnd].kind !== "prose") {
      break;
    }

    const anchor = blocks[embedEnd];
    blocks[embedEnd] = {
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
  const [imageState, setImageState] = useState<"loading" | "loaded" | "error">(
    "loading",
  );
  const imgRef = useRef<HTMLImageElement>(null);
  const linkLabel = embedDisplayCaption(embed, t);
  const isTable = embed.type === "table";

  useEffect(() => {
    setImageState("loading");
  }, [embed.url]);

  useEffect(() => {
    const img = imgRef.current;
    if (img?.complete) {
      setImageState(img.naturalWidth > 0 ? "loaded" : "error");
    }
  }, [embed.url]);

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
        disabled={imageState === "error"}
      >
        {imageState !== "loaded" ? (
          <div
            className={`answer-embed-image-placeholder${
              imageState === "error" ? " answer-embed-image-placeholder--error" : ""
            }`}
            aria-hidden
            role={imageState === "error" ? "img" : undefined}
            aria-label={imageState === "error" ? linkLabel : undefined}
          />
        ) : null}
        <img
          ref={imgRef}
          src={embed.url}
          alt={linkLabel}
          loading="eager"
          className={`answer-embed-image${
            imageState === "loaded" ? "" : " answer-embed-image--hidden"
          }`}
          onLoad={() => setImageState("loaded")}
          onError={() => setImageState("error")}
        />
      </button>
      <ImageLightbox
        open={lightboxOpen}
        src={embed.url}
        alt={linkLabel}
        caption={linkLabel}
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

        const isTable = block.layout === "table-row";
        const compact = block.layout === "figures-row" && block.embeds.length === 1;

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
