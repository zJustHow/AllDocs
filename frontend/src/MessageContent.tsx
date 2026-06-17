import { lazy, memo, Suspense } from "react";
import {
  embedDedupeKey,
  groupSegmentsForLayout,
  segmentsToRenderableContent,
  splitContentIntoSections,
  splitMessageWithCitations,
  stripInlineCitationMarkers,
  type LayoutBlock,
  type MessageSegment,
} from "./citations";
import type { ViewerTarget } from "./citations";
import { useI18n } from "./i18n";
import type { Citation, MessageEmbed } from "./types";

const MarkdownText = lazy(() => import("./MarkdownText"));

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
  const linkLabel =
    embedDisplayCaption(embed, t) ??
    t("viewer.pageHint", { page: embed.page }).trim();
  const isTable = embed.type === "table";

  return (
    <figure
      className={`answer-embed${
        isTable ? " answer-embed--table" : " answer-embed--figure"
      }`}
    >
      <img
        src={embed.url}
        alt={linkLabel}
        loading="lazy"
        className="answer-embed-image"
      />
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
    </figure>
  );
}

interface SegmentListProps {
  segments: MessageSegment[];
  citations: Citation[];
  hasInlineRefs: boolean;
  onOpenDocument: (target: ViewerTarget) => void;
}

function SegmentList({
  segments,
  citations,
  hasInlineRefs,
  onOpenDocument,
}: SegmentListProps) {
  const proseContent = segmentsToRenderableContent(segments);
  if (!proseContent.trim()) return null;

  return (
    <Suspense
      fallback={<div className="streaming-text">{proseContent}</div>}
    >
      <MarkdownText
        content={proseContent}
        inline={hasInlineRefs}
        citations={citations}
        onOpenDocument={onOpenDocument}
      />
    </Suspense>
  );
}

interface LayoutBlockViewProps {
  block: LayoutBlock;
  citations: Citation[];
  hasInlineRefs: boolean;
  onOpenDocument: (target: ViewerTarget) => void;
}

function LayoutBlockView({
  block,
  citations,
  hasInlineRefs,
  onOpenDocument,
}: LayoutBlockViewProps) {
  if (block.kind === "prose") {
    return (
      <div className="answer-prose">
        <SegmentList
          segments={block.segments}
          citations={citations}
          hasInlineRefs={hasInlineRefs}
          onOpenDocument={onOpenDocument}
        />
      </div>
    );
  }

  if (block.embeds.length === 0) {
    return (
      <div className="answer-prose">
        <SegmentList
          segments={block.segments}
          citations={citations}
          hasInlineRefs={hasInlineRefs}
          onOpenDocument={onOpenDocument}
        />
      </div>
    );
  }

  const isTable = block.embeds.some((embed) => embed.type === "table");
  const compact = block.compact && !isTable;

  return (
    <div
      className={`answer-media-block${
        isTable ? " answer-media-block--table" : ""
      }${compact ? " answer-media-block--compact" : ""}`}
    >
      {block.segments.length > 0 ? (
        <div className="answer-media-text">
          <SegmentList
            segments={block.segments}
            citations={citations}
            hasInlineRefs={hasInlineRefs}
            onOpenDocument={onOpenDocument}
          />
        </div>
      ) : null}
      <div className="answer-media-figures">
        {block.embeds.map((embed) => (
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
        const blocks = groupSegmentsForLayout(segments, seenEmbedKeys);

        return (
          <div key={sectionIndex} className="message-section">
            <div className="message-section-body">
              {blocks.map((block, blockIndex) => (
                <LayoutBlockView
                  key={blockIndex}
                  block={block}
                  citations={citations}
                  hasInlineRefs={hasInlineRefs}
                  onOpenDocument={onOpenDocument}
                />
              ))}
            </div>
          </div>
        );
      })}
    </>
  );
}

export default memo(MessageContent);
