import {
  lazy,
  Suspense,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import Composer from "./Composer";
import DocumentViewer from "./DocumentViewer";
import { useDocuments } from "./hooks/useDocuments";
import {
  hideFloatingScrollbarsAfterLayout,
  suppressChatFloatingScrollbars,
  useAutoHideScrollbars,
} from "./hooks/useAutoHideScrollbars";
import { useChat } from "./hooks/useChat";
import { useChatScroll } from "./hooks/useChatScroll";
import { useComposerStackHeight } from "./hooks/useComposerStackHeight";
import { useDocumentViewer } from "./hooks/useDocumentViewer";
import { useRightPanels } from "./hooks/useRightPanels";
import { useSidebarLayout } from "./hooks/useSidebarLayout";
import { useVoice } from "./hooks/useVoice";
import { useI18n, type Locale } from "./i18n";
import {
  AllDocsIcon,
  DocIcon,
  MenuIcon,
  SettingsIcon,
  WarningTriangleIcon,
} from "./icons";
import MessageList from "./MessageList";
import Sidebar from "./Sidebar";
import { useConfirmDialog } from "./useConfirmDialog";
import { PANEL_CLOSE_MS } from "./layout";

const SettingsPanel = lazy(() => import("./SettingsPanel"));
const VIEWER_SCROLLBAR_SUPPRESSION_MS = PANEL_CLOSE_MS + 120;

export default function App() {
  useAutoHideScrollbars();
  const { t, locale, setLocale } = useI18n();
  const { confirm, dialog: confirmDialog } = useConfirmDialog();
  const [error, setError] = useState<string | null>(null);

  const { sidebarOpen, closeSidebar, toggleSidebar } = useSidebarLayout();

  const handleCloseSidebar = () => {
    hideFloatingScrollbarsAfterLayout();
    closeSidebar();
  };

  const handleToggleSidebar = () => {
    hideFloatingScrollbarsAfterLayout();
    toggleSidebar();
  };

  const {
    settingsOpen,
    rightPanelOrder,
    registerRightPanel,
    unregisterRightPanel,
    closeSettings,
    toggleSettings,
  } = useRightPanels();

  const {
    chatAreaRef,
    spacerRef,
    setScrollTargetId,
    registerMessageRef,
    resetSpacer,
  } = useChatScroll();

  const {
    documents,
    selectedDocIds,
    readyDocs,
    statusLabel,
    uploading,
    toggleDoc,
    handleUpload,
    handleDelete,
    handleReindex,
  } = useDocuments({ setError, confirm });

  const { viewerTarget, viewerOpen, openDocument, closeViewer } =
    useDocumentViewer({
      documents,
      registerRightPanel,
      unregisterRightPanel,
    });
  const viewerSlotRef = useRef<HTMLDivElement>(null);
  const [viewerExitWidth, setViewerExitWidth] = useState<number | null>(null);

  const hideScrollbarsForViewerTransition = () => {
    suppressChatFloatingScrollbars(VIEWER_SCROLLBAR_SUPPRESSION_MS);
    hideFloatingScrollbarsAfterLayout();
  };

  const closeViewerWithTransition = (immediate = false) => {
    hideScrollbarsForViewerTransition();
    if (!immediate) {
      const width =
        viewerSlotRef.current
          ?.querySelector<HTMLElement>(".doc-viewer")
          ?.getBoundingClientRect().width ?? 0;
      if (width > 0) setViewerExitWidth(width);
    }
    closeViewer(immediate);
  };

  const handleOpenDocument = (target: Parameters<typeof openDocument>[0]) => {
    openDocument(target);
    hideScrollbarsForViewerTransition();
  };

  const {
    messages,
    setMessages,
    input,
    setInput,
    sessionId,
    setSessionId,
    loading,
    setLoading,
    textareaRef,
    clearChat,
    sendText,
  } = useChat({ selectedDocIds, setScrollTargetId, setError });

  const { recording, voiceStatus, startRecording, stopRecording } = useVoice({
    selectedDocIds,
    sessionId,
    loading,
    setMessages,
    setSessionId,
    setLoading,
    setScrollTargetId,
    setError,
  });

  const rightPanelsToRender = useMemo(() => {
    const panels = [...rightPanelOrder];
    if (!panels.includes("settings")) panels.push("settings");
    if (viewerTarget && !panels.includes("viewer")) panels.push("viewer");
    return panels;
  }, [rightPanelOrder, viewerTarget]);

  const handleNewChat = () => {
    clearChat(() => {
      resetSpacer();
      closeViewerWithTransition();
    });
  };

  const hasMessages = messages.length > 0;
  const composerRef = useRef<HTMLDivElement>(null);

  useComposerStackHeight(
    composerRef,
    `${error ?? ""}|${voiceStatus ?? ""}|${recording}|${hasMessages}`,
  );

  const handleLocaleChange = (next: Locale) => {
    if (next !== locale) setLocale(next);
  };

  return (
    <div
      className={`app ${viewerOpen ? "with-viewer viewer-open" : ""} ${settingsOpen ? "settings-open" : ""}`}
    >
      <div
        className={`sidebar-overlay ${sidebarOpen ? "visible" : ""}`}
        onClick={handleCloseSidebar}
        aria-hidden="true"
      />
      <div
        className={`settings-overlay ${settingsOpen ? "visible" : ""}`}
        onClick={closeSettings}
        aria-hidden="true"
      />

      <Sidebar
        open={sidebarOpen}
        documents={documents}
        selectedDocIds={selectedDocIds}
        readyCount={readyDocs.length}
        uploading={uploading}
        statusLabel={statusLabel}
        onToggle={handleToggleSidebar}
        onNewChat={handleNewChat}
        onUpload={handleUpload}
        onToggleDoc={toggleDoc}
        onReindex={handleReindex}
        onDelete={handleDelete}
      />

      <div className="main">
        <header className="top-bar">
          <button
            className={`icon-btn top-bar-menu ${sidebarOpen ? "hidden" : ""}`}
            onClick={handleToggleSidebar}
            aria-label={sidebarOpen ? undefined : t("sidebar.open")}
            aria-hidden={sidebarOpen}
            tabIndex={sidebarOpen ? -1 : 0}
          >
            <MenuIcon />
          </button>
          <span className="top-bar-title">{t("app.brand")}</span>
          {selectedDocIds.length > 0 ? (
            <span className="top-bar-sub">
              <DocIcon />
              {t("topBar.docsSelected", { count: selectedDocIds.length })}
            </span>
          ) : readyDocs.length > 0 ? (
            <span className="top-bar-sub top-bar-hint">
              <WarningTriangleIcon />
              {t("topBar.selectDocs")}
            </span>
          ) : (
            <span className="top-bar-sub top-bar-hint">
              <WarningTriangleIcon />
              {t("topBar.uploadFirst")}
            </span>
          )}
          <div className="top-bar-spacer" aria-hidden="true" />
          <div
            className="lang-switch"
            role="group"
            aria-label={t("language.label")}
          >
            {(["zh", "en"] as const).map((code) => (
              <button
                key={code}
                type="button"
                className={`lang-switch-btn ${locale === code ? "active" : ""}`}
                onClick={() => handleLocaleChange(code)}
                aria-pressed={locale === code}
              >
                {t(`language.${code}`)}
              </button>
            ))}
          </div>
          <button
            type="button"
            className={`icon-btn settings-btn ${settingsOpen ? "hidden" : ""}`}
            onClick={toggleSettings}
            aria-label={settingsOpen ? undefined : t("settings.open")}
            aria-hidden={settingsOpen}
            tabIndex={settingsOpen ? -1 : 0}
          >
            <SettingsIcon />
          </button>
        </header>

        <div className="chat-shell">
          <div
            className={`chat-area${hasMessages ? "" : " chat-area-empty"}`}
            ref={chatAreaRef}
          >
            {!hasMessages ? (
              <div className="welcome">
                <div className="welcome-logo">
                  <AllDocsIcon size={48} />
                </div>
                <h1>{t("welcome.title")}</h1>
                <p className="welcome-sub">{t("welcome.subtitle")}</p>
              </div>
            ) : (
              <MessageList
                messages={messages}
                scrollRef={chatAreaRef}
                onOpenDocument={handleOpenDocument}
                registerRef={registerMessageRef}
                spacerRef={spacerRef}
              />
            )}
          </div>

          <div className="main-bottom" ref={composerRef}>
            {error ? (
              <div className="status-bar">
                <div className="banner error">{error}</div>
              </div>
            ) : null}

            <Composer
              input={input}
              loading={loading}
              recording={recording}
              voiceStatus={voiceStatus}
              textareaRef={textareaRef}
              onInputChange={setInput}
              onSend={() => sendText()}
              onStartRecording={startRecording}
              onStopRecording={stopRecording}
            />
          </div>
        </div>
      </div>

      {rightPanelsToRender.map((panel) => {
        if (panel === "settings") {
          return (
            <div
              key="settings"
              className={`settings-panel-slot ${settingsOpen ? "is-open" : ""}`}
            >
              <Suspense fallback={null}>
                <SettingsPanel open={settingsOpen} onClose={closeSettings} />
              </Suspense>
            </div>
          );
        }

        if (panel === "viewer" && viewerTarget) {
          return (
            <div
              key="viewer"
              ref={viewerSlotRef}
              className={`doc-viewer-slot ${viewerOpen ? "is-layout-open is-open" : "is-closing"}`}
              style={
                viewerExitWidth
                  ? ({
                      "--viewer-exit-width": `${viewerExitWidth}px`,
                    } as CSSProperties)
                  : undefined
              }
            >
              <DocumentViewer
                key={viewerTarget.documentId}
                target={viewerTarget}
                onClose={() => closeViewerWithTransition()}
              />
            </div>
          );
        }

        return null;
      })}

      {confirmDialog}
    </div>
  );
}
