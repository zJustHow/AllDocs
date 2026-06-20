import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  createVoiceSocket,
  deleteDocument,
  listDocuments,
  reindexDocument,
  streamChat,
  uploadDocument,
} from "./api";
import { createAssistantStreamController } from "./chatStream";
import Composer from "./Composer";
import { type ViewerTarget } from "./citations";
import { highlightRegionsKey } from "./viewerPosition";
import { loadSupportedFormats } from "./fileTypes";
import { useI18n, type Locale } from "./i18n";
import {
  AllDocsIcon,
  DocIcon,
  MenuIcon,
  SettingsIcon,
} from "./icons";
import MessageList from "./MessageList";
import SettingsPanel from "./SettingsPanel";
import Sidebar from "./Sidebar";
import type { ChatMessage, DocumentItem } from "./types";
import { isMobileViewport, MOBILE_BREAKPOINT } from "./layout";
import { useConfirmDialog } from "./useConfirmDialog";

const DocumentViewer = lazy(() => import("./DocumentViewer"));

function newId() {
  if (typeof crypto?.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export default function App() {
  const { t, locale, setLocale, suggestions } = useI18n();
  const { confirm, dialog: confirmDialog } = useConfirmDialog();

  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [viewerTarget, setViewerTarget] = useState<ViewerTarget | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => !isMobileViewport());
  const [settingsOpen, setSettingsOpen] = useState(false);

  const chatAreaRef = useRef<HTMLDivElement>(null);
  const messageRefs = useRef<Map<string, HTMLElement>>(new Map());
  const [scrollTargetId, setScrollTargetId] = useState<string | null>(null);
  const spacerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const viewerCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioQueueRef = useRef<HTMLAudioElement[]>([]);
  const playingRef = useRef(false);
  const voiceDoneRef = useRef(false);
  const userModifiedSelectionRef = useRef(false);

  const statusLabel = useMemo(
    (): Record<DocumentItem["status"], string> => ({
      pending: t("doc.status.pending"),
      processing: t("doc.status.processing"),
      ready: t("doc.status.ready"),
      failed: t("doc.status.failed"),
      deleting: t("doc.status.deleting"),
    }),
    [t],
  );

  const readyDocs = useMemo(
    () => documents.filter((doc) => doc.status === "ready"),
    [documents],
  );

  const indexingDocs = useMemo(
    () =>
      documents.filter(
        (doc) =>
          doc.status === "pending" ||
          doc.status === "processing" ||
          doc.status === "deleting",
      ),
    [documents],
  );

  const refreshDocuments = useCallback(async () => {
    const docs = await listDocuments();
    setDocuments(docs);
    setSelectedDocIds((prev) => {
      const readyIds = docs
        .filter((d) => d.status === "ready")
        .map((d) => d.id);
      if (prev.length === 0 && !userModifiedSelectionRef.current) {
        return readyIds;
      }
      return prev.filter((id) => readyIds.includes(id));
    });
  }, []);

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`);
    const onBreakpointChange = (event: MediaQueryListEvent) => {
      if (event.matches) setSidebarOpen(false);
    };
    mq.addEventListener("change", onBreakpointChange);
    return () => mq.removeEventListener("change", onBreakpointChange);
  }, []);

  useEffect(() => {
    void loadSupportedFormats();
    refreshDocuments().catch((err) => setError(String(err)));

    const intervalMs = indexingDocs.length > 0 ? 500 : 5000;
    let timer: ReturnType<typeof setInterval> | null = null;

    const startPolling = () => {
      if (timer) return;
      timer = setInterval(() => {
        if (document.visibilityState !== "visible") return;
        refreshDocuments().catch(() => undefined);
      }, intervalMs);
    };

    const stopPolling = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        refreshDocuments().catch(() => undefined);
        startPolling();
      } else {
        stopPolling();
      }
    };

    if (document.visibilityState === "visible") {
      startPolling();
    }
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      stopPolling();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [refreshDocuments, indexingDocs.length]);

  const scrollUserMessageToTop = useCallback((userMessageId: string) => {
    const messageEl = messageRefs.current.get(userMessageId);
    if (!messageEl) return;
    messageEl.scrollIntoView({ block: "start", behavior: "instant" });
  }, []);

  useEffect(() => {
    if (!scrollTargetId) return;

    const layoutAndScroll = () => {
      const container = chatAreaRef.current;
      const messageEl = messageRefs.current.get(scrollTargetId);
      const spacer = spacerRef.current;
      if (!messageEl) return false;

      if (container && spacer) {
        const topGap =
          parseFloat(
            getComputedStyle(document.documentElement).getPropertyValue(
              "--chat-content-top",
            ),
          ) || 32;
        const room =
          container.clientHeight -
          messageEl.getBoundingClientRect().height -
          topGap -
          24;
        spacer.style.minHeight = `${Math.max(room, 0)}px`;
      }

      scrollUserMessageToTop(scrollTargetId);
      setScrollTargetId(null);
      return true;
    };

    requestAnimationFrame(() => {
      if (layoutAndScroll()) return;
      requestAnimationFrame(() => {
        layoutAndScroll();
      });
    });
  }, [scrollTargetId, scrollUserMessageToTop]);

  useEffect(
    () => () => {
      if (viewerCloseTimerRef.current)
        clearTimeout(viewerCloseTimerRef.current);
    },
    [],
  );

  const closeViewer = useCallback((immediate = false) => {
    setViewerOpen(false);
    if (viewerCloseTimerRef.current) clearTimeout(viewerCloseTimerRef.current);
    if (immediate) {
      setViewerTarget(null);
      viewerCloseTimerRef.current = null;
      return;
    }
    viewerCloseTimerRef.current = setTimeout(() => {
      setViewerTarget(null);
      viewerCloseTimerRef.current = null;
    }, 320);
  }, []);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }, [input]);

  const playNextAudio = useCallback(() => {
    if (playingRef.current) return;
    const next = audioQueueRef.current.shift();
    if (!next) return;
    playingRef.current = true;
    next.onended = () => {
      playingRef.current = false;
      playNextAudio();
    };
    next.play().catch(() => {
      playingRef.current = false;
      playNextAudio();
    });
  }, []);

  const enqueueAudio = useCallback(
    (base64: string) => {
      const audio = new Audio(`data:audio/wav;base64,${base64}`);
      audioQueueRef.current.push(audio);
      playNextAudio();
    },
    [playNextAudio],
  );

  const toggleDoc = useCallback((docId: string) => {
    userModifiedSelectionRef.current = true;
    setSelectedDocIds((prev) =>
      prev.includes(docId)
        ? prev.filter((id) => id !== docId)
        : [...prev, docId],
    );
  }, []);

  const handleUpload = useCallback(async (file: File | null) => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await uploadDocument(file);
      await refreshDocuments();
    } catch (err) {
      setError(String(err));
    } finally {
      setUploading(false);
    }
  }, [refreshDocuments]);

  const handleDelete = useCallback(async (docId: string) => {
    const confirmed = await confirm({
      title: t("sidebar.deleteDoc"),
      message: t("sidebar.deleteConfirm"),
      confirmLabel: t("sidebar.deleteDoc"),
      variant: "danger",
    });
    if (!confirmed) return;
    setSelectedDocIds((prev) => prev.filter((id) => id !== docId));
    await deleteDocument(docId);
    await refreshDocuments();
  }, [confirm, refreshDocuments, t]);

  const handleReindex = useCallback(async (docId: string) => {
    const confirmed = await confirm({
      title: t("sidebar.reindexDoc"),
      message: t("sidebar.reindexConfirm"),
      confirmLabel: t("sidebar.reindexDoc"),
    });
    if (!confirmed) return;
    setError(null);
    try {
      await reindexDocument(docId);
      await refreshDocuments();
    } catch (err) {
      setError(String(err));
    }
  }, [confirm, refreshDocuments, t]);

  const clearChat = () => {
    setMessages([]);
    setSessionId(null);
    setError(null);
    setInput("");
    setScrollTargetId(null);
    if (spacerRef.current) spacerRef.current.style.minHeight = "";
    closeViewer(true);
  };

  const sendText = async (textOverride?: string) => {
    const text = (textOverride ?? input).trim();
    if (!text || loading) return;
    if (selectedDocIds.length === 0) {
      setError(t("chat.selectDocError"));
      return;
    }

    setError(null);
    setInput("");
    setLoading(true);

    let assistantId: string | null = null;
    let stream: ReturnType<typeof createAssistantStreamController> | null = null;
    try {
      const userMessage: ChatMessage = {
        id: newId(),
        role: "user",
        content: text,
      };
      setScrollTargetId(userMessage.id);
      assistantId = newId();
      setMessages((prev) => [
        ...prev,
        userMessage,
        {
          id: assistantId!,
          role: "assistant",
          content: "",
          streaming: true,
          agentSteps: [],
          agentRunning: true,
        },
      ]);

      stream = createAssistantStreamController({
        assistantId: assistantId!,
        setMessages,
        setSessionId,
        setError,
        setLoading,
      });

      await streamChat(text, sessionId, selectedDocIds, stream.handlers);
    } catch (err) {
      stream?.flush();
      setError(String(err));
      if (assistantId) {
        setMessages((prev) => prev.filter((msg) => msg.id !== assistantId));
      }
    } finally {
      setLoading(false);
    }
  };

  const finishVoice = useCallback((message?: string) => {
    if (voiceDoneRef.current) return;
    voiceDoneRef.current = true;
    if (message) setError(message);
    setLoading(false);
  }, []);

  const sendVoice = async (blob: Blob) => {
    if (selectedDocIds.length === 0) {
      setError(t("chat.selectDocError"));
      return;
    }

    setLoading(true);
    setError(null);
    audioQueueRef.current = [];
    voiceDoneRef.current = false;

    let ws: WebSocket | null = null;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    let stream: ReturnType<typeof createAssistantStreamController> | null = null;

    const cleanup = (message?: string) => {
      stream?.flush();
      if (timeoutId) clearTimeout(timeoutId);
      if (ws && ws.readyState === WebSocket.OPEN) ws.close();
      finishVoice(message);
    };

    try {
      const reader = new FileReader();
      const base64 = await new Promise<string>((resolve, reject) => {
        reader.onload = () => {
          const result = reader.result as string;
          resolve(result.split(",")[1] ?? "");
        };
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
      });

      ws = createVoiceSocket();
      const assistantId = newId();
      stream = createAssistantStreamController({
        assistantId,
        setMessages,
        setSessionId,
        setError,
        setLoading,
        onAudio: enqueueAudio,
      });

      timeoutId = setTimeout(() => {
        cleanup(t("voice.timeout"));
      }, 300_000);

      ws.onopen = () => {
        ws?.send(
          JSON.stringify({
            type: "audio",
            data: base64,
            session_id: sessionId,
            doc_ids: selectedDocIds,
            with_audio: true,
          }),
        );
      };

      ws.onmessage = (event) => {
        let payload: { type: string; [key: string]: unknown };
        try {
          payload = JSON.parse(event.data);
        } catch {
          cleanup(t("voice.parseFailed"));
          return;
        }

        if (payload.type === "transcript") {
          const userMessageId = newId();
          setScrollTargetId(userMessageId);
          setMessages((prev) => [
            ...prev,
            {
              id: userMessageId,
              role: "user",
              content: payload.text as string,
            },
            {
              id: assistantId,
              role: "assistant",
              content: "",
              streaming: true,
              citations: [],
              agentSteps: [],
              agentRunning: true,
            },
          ]);
          return;
        }

        const result = stream?.dispatchPayload(payload) ?? "continue";
        if (result === "done") {
          cleanup();
          return;
        }
        if (result === "error") {
          cleanup(payload.message as string);
        }
      };

      ws.onerror = () => {
        cleanup(t("voice.connectionFailed"));
      };

      ws.onclose = () => {
        if (!voiceDoneRef.current) {
          cleanup(t("voice.disconnected"));
        }
      };
    } catch (err) {
      cleanup(String(err));
    }
  };

  const startRecording = async () => {
    if (loading || recording) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    audioChunksRef.current = [];
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) audioChunksRef.current.push(event.data);
    };
    recorder.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop());
      const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
      await sendVoice(blob);
    };
    mediaRecorderRef.current = recorder;
    recorder.start();
    setRecording(true);
  };

  const stopRecording = () => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    recorder.requestData();
    recorder.stop();
    setRecording(false);
  };

  const openDocument = useCallback((target: ViewerTarget) => {
    const doc = documents.find((d) => d.id === target.documentId);
    if (viewerCloseTimerRef.current) {
      clearTimeout(viewerCloseTimerRef.current);
      viewerCloseTimerRef.current = null;
    }

    const nextTarget = {
      ...target,
      contentType: doc?.content_type ?? target.contentType ?? null,
      pageCount: doc?.page_count ?? target.pageCount ?? null,
    };
    const alreadyOpen = viewerTarget !== null && viewerOpen;

    setViewerTarget(nextTarget);

    if (alreadyOpen) {
      setViewerOpen(true);
      return;
    }

    requestAnimationFrame(() => setViewerOpen(true));
  }, [documents, viewerTarget, viewerOpen]);

  const registerMessageRef = useCallback((id: string, el: HTMLElement | null) => {
    if (el) messageRefs.current.set(id, el);
    else messageRefs.current.delete(id);
  }, []);

  const toggleSidebar = () => setSidebarOpen((prev) => !prev);

  const closeSidebarOnMobile = () => {
    if (isMobileViewport()) setSidebarOpen(false);
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
        onClick={() => setSidebarOpen(false)}
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
        onNewChat={clearChat}
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
            className="icon-btn settings-btn"
            onClick={() => setSettingsOpen(true)}
            aria-label={t("settings.open")}
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

      {viewerTarget && (
        <div className={`doc-viewer-slot ${viewerOpen ? "is-open" : ""}`}>
          <Suspense fallback={null}>
            <DocumentViewer
              key={`${viewerTarget.documentId}:${viewerTarget.page ?? 0}:${highlightRegionsKey(viewerTarget.regions)}`}
              target={viewerTarget}
              onClose={closeViewer}
            />
          </Suspense>
        </div>
      )}

      {confirmDialog}
      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
