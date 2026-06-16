import {
  citationToViewerTarget,
  formatDocumentNameLabel,
  splitMessageWithCitations,
  stripInlineCitationMarkers,
} from "./citations";
import type { ViewerTarget } from "./citations";
import { useI18n } from "./i18n";
import { PdfBadgeIcon } from "./icons";
import type { Citation, MessageEmbed } from "./types";

interface MessageContentProps {
  content: string;
  citations?: Citation[];
  embeds?: MessageEmbed[];
  streaming?: boolean;
  onOpenDocument: (target: ViewerTarget) => void;
}

export default function MessageContent({
  content,
  citations = [],
  embeds = [],
  streaming = false,
  onOpenDocument,
}: MessageContentProps) {
  const { t } = useI18n();

  if (streaming) {
    return <>{stripInlineCitationMarkers(content)}</>;
  }

  const segments = splitMessageWithCitations(content, citations, {
    hideUnmatched: true,
    embeds,
  });

  return (
    <>
      {segments.map((segment, index) => {
        if (segment.type === "text") {
          return <span key={index}>{segment.value}</span>;
        }

        if (segment.type === "embed") {
          const caption =
            segment.embed.caption ??
            (segment.embed.document_name
              ? `${segment.embed.document_name} p.${segment.embed.page}`
              : undefined);
          return (
            <figure key={index} className="answer-embed">
              <img
                src={segment.embed.url}
                alt={caption ?? t("viewer.pageHint", { page: segment.embed.page })}
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
        }

        const pageHint = segment.citation.page
          ? t("viewer.pageHint", { page: segment.citation.page })
          : "";
        const label = formatDocumentNameLabel(segment.citation.document_name);

        return (
          <button
            key={index}
            type="button"
            className="citation-badge"
            title={`${segment.citation.document_name}${pageHint}${
              segment.citation.section ? ` · ${segment.citation.section}` : ""
            }\n${segment.citation.snippet}`}
            onClick={() =>
              onOpenDocument(citationToViewerTarget(segment.citation))
            }
          >
            <PdfBadgeIcon />
            {label}
          </button>
        );
      })}
    </>
  );
}
