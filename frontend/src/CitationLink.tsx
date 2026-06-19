import { memo } from "react";
import {
  citationToViewerTarget,
  formatCitationLabel,
  formatCitationSnippetExcerpt,
} from "./citations";
import type { ViewerTarget } from "./citations";
import { useI18n } from "./i18n";
import type { Citation } from "./types";

function citationTooltip(citation: Citation, pageHint: string): string {
  return `${citation.document_name}${pageHint}${
    citation.section ? ` · ${citation.section}` : ""
  }\n${formatCitationSnippetExcerpt(citation.snippet)}`;
}

interface CitationLinkProps {
  citation: Citation;
  index: number;
  onOpenDocument: (target: ViewerTarget) => void;
}

function CitationLink({ citation, index, onOpenDocument }: CitationLinkProps) {
  const { t } = useI18n();
  const pageHint = citation.page
    ? t("viewer.pageHint", { page: citation.page })
    : "";

  return (
    <button
      type="button"
      className="citation-link"
      title={citationTooltip(citation, pageHint)}
      onClick={() => onOpenDocument(citationToViewerTarget(citation))}
    >
      {formatCitationLabel(index)}
    </button>
  );
}

export default memo(CitationLink);
