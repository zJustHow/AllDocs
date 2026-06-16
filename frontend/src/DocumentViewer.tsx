import { useEffect, useMemo, useState } from "react";
import { getDocumentFileUrl } from "./api";
import type { ViewerTarget } from "./citations";
import { getPreviewMode } from "./fileTypes";
import { useI18n } from "./i18n";
import { CloseIcon, ZoomInIcon, ZoomOutIcon } from "./icons";

interface DocumentViewerProps {
  target: ViewerTarget;
  onClose: () => void;
}

const ZOOM_MIN = 50;
const ZOOM_MAX = 200;
const ZOOM_STEP = 25;

const fileUrlCache = new Map<string, string>();

export default function DocumentViewer({ target, onClose }: DocumentViewerProps) {
  const { t } = useI18n();
  const previewMode = getPreviewMode(target.documentName, target.contentType);
  const [fileUrl, setFileUrl] = useState<string | null>(
    () => fileUrlCache.get(target.documentId) ?? null,
  );
  const [textContent, setTextContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(() => !fileUrlCache.has(target.documentId));
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(target.page ?? 1);
  const [pageInput, setPageInput] = useState(String(target.page ?? 1));
  const [zoom, setZoom] = useState(100);

  const pageCount = target.pageCount ?? null;
  const showPageToolbar = previewMode === "pdf" && pageCount !== null;

  useEffect(() => {
    let active = true;
    const cached = fileUrlCache.get(target.documentId);

    if (cached) {
      setFileUrl(cached);
      setLoading(false);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);
    setTextContent(null);

    getDocumentFileUrl(target.documentId)
      .then(async (url) => {
        if (!active) return;
        fileUrlCache.set(target.documentId, url);
        setFileUrl(url);
        if (previewMode === "text") {
          const response = await fetch(url);
          const text = await response.text();
          if (active) setTextContent(text);
        }
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
  }, [target.documentId, previewMode]);

  const iframeSrc = useMemo(() => {
    if (!fileUrl || previewMode !== "pdf") return undefined;
    return `${fileUrl}#page=${currentPage}`;
  }, [fileUrl, currentPage, previewMode]);

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
            {loading && !fileUrl && <p className="doc-viewer-status">{t("viewer.loading")}</p>}
            {error && <p className="doc-viewer-status error-text">{error}</p>}
            {iframeSrc && !error && (
              <iframe
                key={`${target.documentId}-${currentPage}`}
                title={target.documentName}
                src={iframeSrc}
                className="doc-viewer-frame"
              />
            )}
            {fileUrl && previewMode === "image" && !error && (
              <img
                src={fileUrl}
                alt={target.documentName}
                className="doc-viewer-image"
              />
            )}
            {previewMode === "text" && textContent && !error && (
              <pre className="doc-viewer-text">{textContent}</pre>
            )}
            {previewMode === "unsupported" && fileUrl && !error && (
              <div className="doc-viewer-status">
                <p>{t("viewer.unsupported")}</p>
                <a href={fileUrl} download={target.documentName} className="doc-viewer-download">
                  {t("viewer.download")}
                </a>
              </div>
            )}
          </div>

          {!loading && !error && fileUrl && showPageToolbar && (
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
