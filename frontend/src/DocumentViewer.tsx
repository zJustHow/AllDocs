import { useEffect, useMemo, useState } from "react";
import { documentFileUrl, documentPageRenderUrl } from "./api";
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
const BASE_RENDER_SCALE = 2;

export default function DocumentViewer({ target, onClose }: DocumentViewerProps) {
  const { t } = useI18n();
  const previewMode = getPreviewMode(target.documentName, target.contentType);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(previewMode === "text");
  const [pageLoading, setPageLoading] = useState(previewMode === "pdf");
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(target.page ?? 1);
  const [pageInput, setPageInput] = useState(String(target.page ?? 1));
  const [zoom, setZoom] = useState(100);

  const pageCount = target.pageCount ?? null;
  const showPageToolbar = previewMode === "pdf" && pageCount !== null;
  const fileUrl = documentFileUrl(target.documentId);

  const renderScale = useMemo(
    () => Math.min(4, Math.max(0.5, (zoom / 100) * BASE_RENDER_SCALE)),
    [zoom],
  );

  const pageImageUrl = useMemo(() => {
    if (previewMode !== "pdf") return null;
    return documentPageRenderUrl(target.documentId, currentPage, renderScale);
  }, [previewMode, target.documentId, currentPage, renderScale]);

  useEffect(() => {
    const page = target.page ?? 1;
    setCurrentPage(page);
    setPageInput(String(page));
  }, [target.documentId, target.page]);

  useEffect(() => {
    if (previewMode !== "text") {
      setTextContent(null);
      setLoading(false);
      return;
    }

    let active = true;
    setLoading(true);
    setError(null);

    fetch(fileUrl)
      .then(async (response) => {
        if (!response.ok) throw new Error(t("errors.loadDocumentFailed"));
        return response.text();
      })
      .then((text) => {
        if (active) setTextContent(text);
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
  }, [fileUrl, previewMode, t]);

  useEffect(() => {
    if (previewMode === "pdf") setPageLoading(true);
  }, [pageImageUrl, previewMode]);

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

  const showToolbar =
    !error &&
    !loading &&
    (previewMode === "pdf" ? !pageLoading : previewMode !== "text" || Boolean(textContent));

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
          <div
            className="doc-viewer-canvas"
            style={previewMode === "pdf" ? undefined : { transform: `scale(${zoom / 100})` }}
          >
            {loading && previewMode === "text" && (
              <p className="doc-viewer-status">{t("viewer.loading")}</p>
            )}
            {error && <p className="doc-viewer-status error-text">{error}</p>}
            {previewMode === "pdf" && pageImageUrl && !error && (
              <>
                {pageLoading ? (
                  <p className="doc-viewer-status">{t("viewer.loading")}</p>
                ) : null}
                <img
                  key={pageImageUrl}
                  src={pageImageUrl}
                  alt={`${target.documentName} p.${currentPage}`}
                  className="doc-viewer-image"
                  onLoad={() => setPageLoading(false)}
                  onError={() => {
                    setPageLoading(false);
                    setError(t("errors.loadDocumentFailed"));
                  }}
                />
              </>
            )}
            {previewMode === "image" && !error && (
              <img
                src={fileUrl}
                alt={target.documentName}
                className="doc-viewer-image"
              />
            )}
            {previewMode === "text" && textContent && !error && (
              <pre className="doc-viewer-text">{textContent}</pre>
            )}
            {previewMode === "unsupported" && !error && (
              <div className="doc-viewer-status">
                <p>{t("viewer.unsupported")}</p>
                <a href={fileUrl} download={target.documentName} className="doc-viewer-download">
                  {t("viewer.download")}
                </a>
              </div>
            )}
          </div>

          {showPageToolbar && showToolbar && (
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
