import {
  citationToViewerTarget,
  formatCitationLabel,
  getCitationIndex,
  splitMessageWithCitations,
} from "./citations";
import type { ViewerTarget } from "./citations";
import { PdfBadgeIcon } from "./icons";
import type { Citation } from "./types";

interface MessageContentProps {
  content: string;
  citations?: Citation[];
  onOpenDocument: (target: ViewerTarget) => void;
}

export default function MessageContent({
  content,
  citations = [],
  onOpenDocument,
}: MessageContentProps) {
  const segments = splitMessageWithCitations(content, citations);

  return (
    <>
      {segments.map((segment, index) => {
        if (segment.type === "text") {
          return <span key={index}>{segment.value}</span>;
        }

        const pageHint = segment.citation.page ? ` · 第 ${segment.citation.page} 页` : "";

        const citationIndex = getCitationIndex(segment.citation, citations);
        const label =
          citationIndex >= 0
            ? formatCitationLabel(citationIndex)
            : (segment.value.match(/\[\d+\]/)?.[0] ?? "[?]");

        return (
          <button
            key={index}
            type="button"
            className="citation-badge"
            title={`${segment.citation.document_name}${pageHint}${
              segment.citation.section ? ` · ${segment.citation.section}` : ""
            }\n${segment.citation.snippet}`}
            onClick={() => onOpenDocument(citationToViewerTarget(segment.citation))}
          >
            <PdfBadgeIcon />
            PDF {label}
          </button>
        );
      })}
    </>
  );
}
