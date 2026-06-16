import { useEffect, useMemo, useState } from "react";
import { getDocumentFileUrl } from "./api";
import type { ViewerTarget } from "./citations";
import { useI18n } from "./i18n";
import { CloseIcon, ZoomInIcon, ZoomOutIcon } from "./icons";

interface DocumentViewerProps {
  target: ViewerTarget;
  onClose: () => void;
}

const ZOOM_MIN = 50;
const ZOOM_MAX = 200;
const ZOOM_STEP = 25;

const pdfUrlCache = new Map<string, string>();

export default function DocumentViewer({ target, onClose }: DocumentViewerProps) {
  const { t } = useI18n();
  const [pdfUrl, setPdfUrl] = useState<string | null>(
    () => pdfUrlCache.get(target.documentId) ?? null,
  );
  const [loading, setLoading] = useState(() => !pdfUrlCache.has(target.documentId));
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(target.page ?? 1);
  const [pageInput, setPageInput] = useState(String(target.page ?? 1));
  const [zoom, setZoom] = useState(100);

  const pageCount = target.pageCount ?? null;

  useEffect(() => {
    let active = true;
    const cached = pdfUrlCache.get(target.documentId);

    if (cached) {
      setPdfUrl(cached);
      setLoading(false);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    getDocumentFileUrl(target.documentId)
      .then((url) => {
        if (!active) return;
        pdfUrlCache.set(target.documentId, url);
        setPdfUrl(url);
      })
      .catch((err) => {
        if (active) setError(String(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [target.documentId]);

  const iframeSrc = useMemo(() => {
    if (!pdfUrl) return undefined;
    return `${pdfUrl}#page=${currentPage}`;
  }, [pdfUrl, currentPage]);

  const commitPage = (raw: string) => {
    const parsed = Number.parseInt(raw, 10);
    if (Number.isNaN(parsed)) {
      setPageInput(String(currentPage));
      return;
    }
    const max = pageCount ?? parsed;
    const next = Math.min(Math.max(1, parsed), max);
    setCurrentPage(next);
    setPageInput(String(next));
  };

  const adjustZoom = (delta: number) => {
    setZoom((prev) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, prev + delta)));
  };

  return (
    <aside className="doc-viewer">
      <div className="doc-viewer-top">
        <div className="doc-viewer-meta">
          <span className="doc-viewer-name">{target.documentName}</span>
          {target.section ? <span className="doc-viewer-section">{target.section}</span> : null}
        </div>
        <button className="doc-viewer-close" onClick={onClose} aria-label={t("viewer.close")}>
          <CloseIcon />
        </button>
      </div>

      <div className="doc-viewer-shell">
        <div className="doc-viewer-stage">
          <div className="doc-viewer-canvas" style={{ transform: `scale(${zoom / 100})` }}>
            {loading && !pdfUrl && <p className="doc-viewer-status">{t("viewer.loading")}</p>}
            {error && <p className="doc-viewer-status error-text">{error}</p>}
            {iframeSrc && !error && (
              <iframe
                key={`${target.documentId}-${currentPage}`}
                title={target.documentName}
                src={iframeSrc}
                className="doc-viewer-frame"
              />
            )}
          </div>

          {!loading && !error && pdfUrl && (
            <div className="doc-viewer-toolbar">
              <span className="doc-viewer-toolbar-label">{t("viewer.pageLabel")}</span>
              <input
                className="doc-viewer-page-input"
                type="text"
                inputMode="numeric"
                value={pageInput}
                onChange={(e) => setPageInput(e.target.value)}
                onBlur={() => commitPage(pageInput)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    commitPage(pageInput);
                    (e.target as HTMLInputElement).blur();
                  }
                }}
                aria-label={t("viewer.page")}
              />
              <span className="doc-viewer-page-total">/ {pageCount ?? "—"}</span>
              <span className="doc-viewer-toolbar-divider" aria-hidden="true" />
              <button
                type="button"
                className="doc-viewer-toolbar-btn"
                onClick={() => adjustZoom(-ZOOM_STEP)}
                disabled={zoom <= ZOOM_MIN}
                aria-label={t("viewer.zoomOut")}
              >
                <ZoomOutIcon />
              </button>
              <span className="doc-viewer-zoom-label">{zoom}%</span>
              <button
                type="button"
                className="doc-viewer-toolbar-btn"
                onClick={() => adjustZoom(ZOOM_STEP)}
                disabled={zoom >= ZOOM_MAX}
                aria-label={t("viewer.zoomIn")}
              >
                <ZoomInIcon />
              </button>
            </div>
          )}
        </div>
      </div>

      {target.snippet && (
        <div className="doc-viewer-snippet">
          <p>{target.snippet}</p>
        </div>
      )}
    </aside>
  );
}
