import { memo } from "react";
import { UPLOAD_ACCEPT } from "./fileTypes";
import { useI18n } from "./i18n";
import {
  MenuIcon,
  NewChatIcon,
  PlusIcon,
  ReindexIcon,
  TrashIcon,
} from "./icons";
import type { DocumentItem } from "./types";

interface SidebarProps {
  open: boolean;
  documents: DocumentItem[];
  selectedDocIds: string[];
  readyCount: number;
  uploading: boolean;
  statusLabel: Record<DocumentItem["status"], string>;
  onToggle: () => void;
  onNewChat: () => void;
  onUpload: (file: File | null) => void;
  onToggleDoc: (docId: string) => void;
  onReindex: (docId: string) => void;
  onDelete: (docId: string) => void;
}

function Sidebar({
  open,
  documents,
  selectedDocIds,
  readyCount,
  uploading,
  statusLabel,
  onToggle,
  onNewChat,
  onUpload,
  onToggleDoc,
  onReindex,
  onDelete,
}: SidebarProps) {
  const { t } = useI18n();

  return (
    <aside className={`sidebar ${open ? "open" : "collapsed"}`}>
      <div className="sidebar-inner">
        <div className="sidebar-top">
          <button
            className="icon-btn"
            onClick={onToggle}
            aria-label={t("sidebar.collapse")}
          >
            <MenuIcon />
          </button>
        </div>

        <button className="new-chat-btn" onClick={onNewChat}>
          <NewChatIcon />
          {t("sidebar.newChat")}
        </button>

        <label className="upload-btn">
          <input
            type="file"
            accept={UPLOAD_ACCEPT}
            hidden
            disabled={uploading}
            onChange={(e) => onUpload(e.target.files?.[0] ?? null)}
          />
          <PlusIcon />
          <span>
            {uploading ? t("sidebar.uploading") : t("sidebar.uploadDoc")}
          </span>
        </label>
        <p className="upload-hint">{t("sidebar.uploadHint")}</p>

        <div className="sidebar-section-label">
          {t("sidebar.docLibrary", { count: readyCount })}
        </div>

        <div className="doc-list">
          {documents.length === 0 && (
            <p className="doc-list-empty">{t("sidebar.emptyList")}</p>
          )}
          {documents.map((doc) => (
            <div key={doc.id} className={`doc-item ${doc.status}`}>
              <label className="doc-main">
                <input
                  type="checkbox"
                  className="doc-checkbox"
                  checked={selectedDocIds.includes(doc.id)}
                  disabled={doc.status !== "ready"}
                  onChange={() => onToggleDoc(doc.id)}
                />
                <div className="doc-body">
                  <strong className="doc-name" title={doc.name}>
                    {doc.name}
                  </strong>
                  <div className="doc-meta">
                    <span className={`status ${doc.status}`}>
                      {statusLabel[doc.status]}
                    </span>
                    {doc.page_count ? (
                      <span className="muted">
                        {t("doc.pages", { count: doc.page_count })}
                      </span>
                    ) : null}
                    {doc.ocr_pages ? (
                      <span className="muted">OCR {doc.ocr_pages}</span>
                    ) : null}
                  </div>
                  {(doc.status === "pending" ||
                    doc.status === "processing") && (
                    <div className="index-progress">
                      <div className="index-progress-bar">
                        <div
                          className="index-progress-fill"
                          style={{
                            width: `${doc.status === "pending" ? 0 : doc.progress}%`,
                          }}
                        />
                      </div>
                      <span className="index-progress-label">
                        {doc.progress_message ??
                          (doc.status === "pending"
                            ? t("doc.status.pending")
                            : t("doc.indexing"))}
                        {doc.status === "processing"
                          ? ` ${doc.progress}%`
                          : ""}
                      </span>
                    </div>
                  )}
                  {doc.error_message ? (
                    <span className="error-text">{doc.error_message}</span>
                  ) : null}
                </div>
              </label>
              <div className="doc-actions">
                {(doc.status === "ready" || doc.status === "failed") && (
                  <button
                    type="button"
                    className="doc-action-btn"
                    onClick={() => onReindex(doc.id)}
                    title={t("sidebar.reindexDoc")}
                    aria-label={t("sidebar.reindexDoc")}
                  >
                    <ReindexIcon />
                  </button>
                )}
                <button
                  type="button"
                  className="doc-action-btn danger"
                  onClick={() => onDelete(doc.id)}
                  disabled={doc.status === "deleting"}
                  title={t("sidebar.deleteDoc")}
                  aria-label={t("sidebar.deleteDoc")}
                >
                  <TrashIcon />
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="sidebar-foot">
          <span>{t("app.tagline")}</span>
        </div>
      </div>
    </aside>
  );
}

export default memo(Sidebar);
