import { useEffect, useState } from "react";
import { getDocumentFileUrl } from "./api";
import type { ViewerTarget } from "./citations";

interface DocumentViewerProps {
  target: ViewerTarget;
  onClose: () => void;
}

export default function DocumentViewer({ target, onClose }: DocumentViewerProps) {
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;

    setLoading(true);
    setError(null);
    setPdfUrl(null);

    getDocumentFileUrl(target.documentId)
      .then((url) => {
        if (!active) {
          URL.revokeObjectURL(url);
          return;
        }
        objectUrl = url;
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
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [target.documentId]);

  const pageLabel = target.page ? `第 ${target.page} 页` : "文档";
  const sectionLabel = target.section ? ` · ${target.section}` : "";
  const iframeSrc = pdfUrl
    ? target.page
      ? `${pdfUrl}#page=${target.page}`
      : pdfUrl
    : undefined;

  return (
    <aside className="doc-viewer">
      <header className="doc-viewer-header">
        <div>
          <h2>{target.documentName}</h2>
          <p>
            {pageLabel}
            {sectionLabel}
          </p>
        </div>
        <button className="ghost" onClick={onClose} aria-label="关闭文档预览">
          关闭
        </button>
      </header>

      {target.snippet && (
        <div className="doc-viewer-snippet">
          <span>引用片段</span>
          <p>{target.snippet}</p>
        </div>
      )}

      <div className="doc-viewer-body">
        {loading && <p className="muted doc-viewer-status">加载文档中...</p>}
        {error && <p className="doc-viewer-status error-text">{error}</p>}
        {!loading && !error && iframeSrc && (
          <iframe title={target.documentName} src={iframeSrc} className="doc-viewer-frame" />
        )}
      </div>
    </aside>
  );
}
