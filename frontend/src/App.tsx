import {
  lazy,
  Suspense,
  useMemo,
  useState,
} from "react";
import Composer from "./Composer";
import { highlightRegionsKey } from "./viewerPosition";
import { useDocuments } from "./hooks/useDocuments";
import { useChat } from "./hooks/useChat";
import { useChatScroll } from "./hooks/useChatScroll";
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
} from "./icons";
import MessageList from "./MessageList";
import Sidebar from "./Sidebar";
import { useConfirmDialog } from "./useConfirmDialog";

const DocumentViewer = lazy(() => import("./DocumentViewer"));
const SettingsPanel = lazy(() => import("./SettingsPanel"));

export default function App() {
  const { t, locale, setLocale, suggestions } = useI18n();
  const { confirm, dialog: confirmDialog } = useConfirmDialog();
  const [error, setError] = useState<string | null>(null);

  const {
    sidebarOpen,
    closeSidebar,
    toggleSidebar,
    closeSidebarOnMobile,
  } = useSidebarLayout();

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
    scrollTargetId,
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

  const {
    viewerTarget,
    viewerOpen,
    openDocument,
    closeViewer,
  } = useDocumentViewer({
    documents,
    registerRightPanel,
    unregisterRightPanel,
  });

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

  const { recording, startRecording, stopRecording } = useVoice({
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
      closeViewer(true);
    });
  };

  const hasMessages = messages.length > 0;

  const handleLocaleChange = (next: Locale) => {
    if (next !== locale) setLocale(next);
  };

  return (
    <div
      className={`app ${viewerOpen ? "with-viewer viewer-open" : ""}`}
    >
      <div
        className={`sidebar-overlay ${sidebarOpen ? "visible" : ""}`}
        onClick={closeSidebar}
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
        onToggle={toggleSidebar}
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
            onClick={toggleSidebar}
            aria-label={sidebarOpen ? undefined : t("sidebar.open")}
            aria-hidden={sidebarOpen}
            tabIndex={sidebarOpen ? -1 : 0}
          >
            <MenuIcon />
          </button>
          <span className="top-bar-title">{t("app.brand")}</span>
          {selectedDocIds.length > 0 ? (
            <span className="top-bar-sub">
              <DocIcon />{" "}
              {t("topBar.docsSelected", { count: selectedDocIds.length })}
            </span>
          ) : (
            <span className="top-bar-sub top-bar-hint">
              {readyDocs.length === 0
                ? t("topBar.uploadFirst")
                : t("topBar.selectDocs")}
            </span>
          )}
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

        <div className="chat-area" ref={chatAreaRef}>
          {!hasMessages ? (
            <div className="welcome">
              <div className="welcome-logo">
                <AllDocsIcon size={48} />
              </div>
              <h1>{t("welcome.title")}</h1>
              <p className="welcome-sub">{t("welcome.subtitle")}</p>
              <div className="suggestions">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    className="suggestion-chip"
                    onClick={() => {
                      setInput(s);
                      closeSidebarOnMobile();
                      sendText(s);
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <MessageList
              key={sessionId ?? "new"}
              messages={messages}
              scrollRef={chatAreaRef}
              scrollTargetId={scrollTargetId}
              onOpenDocument={openDocument}
              registerRef={registerMessageRef}
              spacerRef={spacerRef}
            />
          )}
        </div>

        {error ? (
          <div className="status-bar">
            <div className="banner error">{error}</div>
          </div>
        ) : null}

        <Composer
          input={input}
          loading={loading}
          recording={recording}
          textareaRef={textareaRef}
          onInputChange={setInput}
          onSend={() => sendText()}
          onStartRecording={startRecording}
          onStopRecording={stopRecording}
        />
      </div>

      {rightPanelsToRender.map((panel) => {
        if (panel === "settings") {
          return (
            <Suspense key="settings" fallback={null}>
              <SettingsPanel open={settingsOpen} onClose={closeSettings} />
            </Suspense>
          );
        }

        if (panel === "viewer" && viewerTarget) {
          return (
            <div
              key="viewer"
              className={`doc-viewer-slot ${viewerOpen ? "is-open" : ""}`}
            >
              <Suspense fallback={null}>
                <DocumentViewer
                  key={`${viewerTarget.documentId}:${viewerTarget.page ?? 0}:${highlightRegionsKey(viewerTarget.regions)}`}
                  target={viewerTarget}
                  onClose={() => closeViewer()}
                />
              </Suspense>
            </div>
          );
        }

        return null;
      })}

      {confirmDialog}
    </div>
  );
}
