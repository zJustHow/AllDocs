import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import Composer from "./Composer";
import DocumentViewer from "./DocumentViewer";
import LoginPage from "./auth/LoginPage";
import AuthCallback from "./auth/AuthCallback";
import { useAuth } from "./auth/AuthContext";
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
  ProfileIcon,
  SettingsIcon,
  WarningTriangleIcon,
} from "./icons";
import MessageList from "./MessageList";
import Sidebar from "./Sidebar";
import { useConfirmDialog } from "./useConfirmDialog";
import { PANEL_CLOSE_MS } from "./layout";

import { hasStoredSession } from "./auth/session";
import ProfilePage from "./ProfilePage";
import SettingsPage from "./SettingsPage";
import { AppLink } from "./AppLink";
import { navigate, useAppPath } from "./routing";
const VIEWER_SCROLLBAR_SUPPRESSION_MS = PANEL_CLOSE_MS + 120;

export default function App() {
  const path = useAppPath();
  const { user, loading, isAdmin, logout } = useAuth();
  const bootstrapping = loading && !user;

  useEffect(() => {
    if (!bootstrapping && path === "/settings" && user && !isAdmin) {
      navigate("/");
    }
  }, [bootstrapping, path, user, isAdmin]);

  if (path === "/auth/callback") {
    return <AuthCallback />;
  }

  if (bootstrapping) {
    if (path === "/profile" && hasStoredSession()) {
      return <ProfilePage onLogout={logout} />;
    }
    if (path === "/settings" && hasStoredSession()) {
      return <SettingsPage isAdmin={false} />;
    }
    return (
      <div className="auth-page">
        <div className="auth-loading">{/* i18n not required for bootstrap */}…</div>
      </div>
    );
  }

  if (!user) {
    return <LoginPage />;
  }

  if (path === "/profile") {
    return <ProfilePage onLogout={logout} />;
  }

  if (path === "/settings") {
    if (!isAdmin) {
      return null;
    }
    return <SettingsPage isAdmin />;
  }

  return <MainApp isAdmin={isAdmin} />;
}

interface MainAppProps {
  isAdmin: boolean;
}

function MainApp({ isAdmin }: MainAppProps) {
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

  const { rightPanelOrder, registerRightPanel, unregisterRightPanel } = useRightPanels();

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
  } = useDocuments({ setError, confirm, isAdmin });

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
  } = useChat({ selectedDocIds, setScrollTargetId, setError, isAdmin, readyDocCount: readyDocs.length });

  const { recording, voiceStatus, startRecording, stopRecording } = useVoice({
    selectedDocIds,
    sessionId,
    loading,
    isAdmin,
    readyDocCount: readyDocs.length,
    setMessages,
    setSessionId,
    setLoading,
    setScrollTargetId,
    setError,
  });

  const rightPanelsToRender = useMemo(() => {
    const panels = [...rightPanelOrder];
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
    <div className={`app ${viewerOpen ? "with-viewer viewer-open" : ""}`}>
      <div
        className={`sidebar-overlay ${sidebarOpen ? "visible" : ""}`}
        onClick={handleCloseSidebar}
        aria-hidden="true"
      />

      <Sidebar
        open={sidebarOpen}
        documents={documents}
        readyCount={readyDocs.length}
        uploading={uploading}
        statusLabel={statusLabel}
        isAdmin={isAdmin}
        onToggle={handleToggleSidebar}
        onNewChat={handleNewChat}
        onUpload={handleUpload}
        onToggleDoc={toggleDoc}
        onReindex={handleReindex}
        onDelete={handleDelete}
      />

      <div className="main">
        <div className="top-bar-slot">
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
          {isAdmin && selectedDocIds.length > 0 ? (
            <span className="top-bar-sub">
              <DocIcon />
              {t("topBar.docsSelected", { count: selectedDocIds.length })}
            </span>
          ) : !isAdmin && readyDocs.length > 0 ? (
            <span className="top-bar-sub">
              <DocIcon />
              {t("topBar.allDocs", { count: readyDocs.length })}
            </span>
          ) : isAdmin && readyDocs.length > 0 ? (
            <span className="top-bar-sub top-bar-hint">
              <WarningTriangleIcon />
              {t("topBar.selectDocs")}
            </span>
          ) : isAdmin ? (
            <span className="top-bar-sub top-bar-hint">
              <WarningTriangleIcon />
              {t("topBar.uploadFirst")}
            </span>
          ) : (
            <span className="top-bar-sub top-bar-hint">
              <WarningTriangleIcon />
              {t("topBar.noDocs")}
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
          <AppLink
            href="/profile"
            className="icon-btn profile-btn"
            aria-label={t("profile.open")}
          >
            <ProfileIcon />
          </AppLink>
          {isAdmin ? (
            <AppLink
              href="/settings"
              className="icon-btn settings-btn"
              aria-label={t("settings.open")}
            >
              <SettingsIcon />
            </AppLink>
          ) : null}
          </header>
        </div>

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
