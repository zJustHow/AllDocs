import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createVoiceSocket,
  deleteDocument,
  listDocuments,
  reindexDocument,
  streamChat,
  uploadDocument,
} from "./api";
import { type ViewerTarget } from "./citations";
import DocumentViewer from "./DocumentViewer";
import { UPLOAD_ACCEPT } from "./fileTypes";
import { useI18n, type Locale } from "./i18n";
import {
  AllDocsIcon,
  DocIcon,
  MenuIcon,
  MicIcon,
  NewChatIcon,
  PlusIcon,
  ReindexIcon,
  SendIcon,
  TrashIcon,
} from "./icons";
import AgentSteps from "./AgentSteps";
import MessageContent from "./MessageContent";
import type { AgentStepEvent, ChatMessage, DocumentItem } from "./types";

function newId() {
  if (typeof crypto?.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export default function App() {
  const { t, locale, setLocale, suggestions } = useI18n();

  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [chatStage, setChatStage] = useState<string | null>(null);
  const [voiceStage, setVoiceStage] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [viewerTarget, setViewerTarget] = useState<ViewerTarget | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const chatAreaRef = useRef<HTMLDivElement>(null);
  const messageRefs = useRef<Map<string, HTMLElement>>(new Map());
  const scrollUserMessageIdRef = useRef<string | null>(null);
  const spacerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const viewerCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioQueueRef = useRef<HTMLAudioElement[]>([]);
  const playingRef = useRef(false);
  const voiceDoneRef = useRef(false);

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
      const readyIds = docs.filter((d) => d.status === "ready").map((d) => d.id);
      if (prev.length === 0) return readyIds;
      return prev.filter((id) => readyIds.includes(id));
    });
  }, []);

  useEffect(() => {
    refreshDocuments().catch((err) => setError(String(err)));
    const intervalMs = indexingDocs.length > 0 ? 500 : 5000;
    const timer = setInterval(() => {
      refreshDocuments().catch(() => undefined);
    }, intervalMs);
    return () => clearInterval(timer);
  }, [refreshDocuments, indexingDocs.length]);

  const scrollUserMessageToTop = useCallback((userMessageId: string) => {
    const messageEl = messageRefs.current.get(userMessageId);
    if (!messageEl) return;
    messageEl.scrollIntoView({ block: "start", behavior: "instant" });
  }, []);

  useEffect(() => {
    const userMessageId = scrollUserMessageIdRef.current;
    if (!userMessageId) return;

    requestAnimationFrame(() => {
      const container = chatAreaRef.current;
      const messageEl = messageRefs.current.get(userMessageId);
      const spacer = spacerRef.current;
      if (container && messageEl && spacer) {
        const topGap =
          parseFloat(
            getComputedStyle(document.documentElement).getPropertyValue("--chat-content-top"),
          ) || 32;
        const room =
          container.clientHeight - messageEl.getBoundingClientRect().height - topGap - 24;
        spacer.style.minHeight = `${Math.max(room, 0)}px`;
      }

      requestAnimationFrame(() => {
        scrollUserMessageToTop(userMessageId);
        scrollUserMessageIdRef.current = null;
      });
    });
  }, [messages, scrollUserMessageToTop]);

  useEffect(
    () => () => {
      if (viewerCloseTimerRef.current) clearTimeout(viewerCloseTimerRef.current);
    },
    [],
  );

  const closeViewer = useCallback(() => {
    setViewerOpen(false);
    if (viewerCloseTimerRef.current) clearTimeout(viewerCloseTimerRef.current);
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

  const toggleDoc = (docId: string) => {
    setSelectedDocIds((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId],
    );
  };

  const handleUpload = async (file: File | null) => {
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
  };

  const handleDelete = async (docId: string) => {
    if (!confirm(t("sidebar.deleteConfirm"))) return;
    setSelectedDocIds((prev) => prev.filter((id) => id !== docId));
    await deleteDocument(docId);
    await refreshDocuments();
  };

  const handleReindex = async (docId: string) => {
    if (!confirm(t("sidebar.reindexConfirm"))) return;
    setError(null);
    try {
      await reindexDocument(docId);
      await refreshDocuments();
    } catch (err) {
      setError(String(err));
    }
  };

  const clearChat = () => {
    setMessages([]);
    setSessionId(null);
    setError(null);
    setInput("");
    scrollUserMessageIdRef.current = null;
    if (spacerRef.current) spacerRef.current.style.minHeight = "";
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
    setChatStage(t("chat.thinking"));

    let assistantId: string | null = null;
    try {
      const userMessage: ChatMessage = { id: newId(), role: "user", content: text };
      scrollUserMessageIdRef.current = userMessage.id;
      assistantId = newId();
      setMessages((prev) => [
        ...prev,
        userMessage,
        { id: assistantId!, role: "assistant", content: "", streaming: true, agentSteps: [], agentRunning: true },
      ]);

      await streamChat(text, sessionId, selectedDocIds, {
        onStatus: (stage) => {
          if (stage === "agent") setChatStage(t("chat.agentRunning"));
        },
        onAgentStep: (step) => {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? { ...msg, agentSteps: [...(msg.agentSteps ?? []), step] }
                : msg,
            ),
          );
        },
        onCitations: (citations) => {
          setMessages((prev) =>
            prev.map((msg) => (msg.id === assistantId ? { ...msg, citations } : msg)),
          );
        },
        onDelta: (delta) => {
          setChatStage(t("chat.generating"));
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? { ...msg, content: msg.content + delta, agentRunning: false }
                : msg,
            ),
          );
        },
        onDone: ({ sessionId: sid, content, citations }) => {
          setSessionId(sid);
          setChatStage(null);
          setLoading(false);
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? {
                    ...msg,
                    streaming: false,
                    agentRunning: false,
                    content: content ?? msg.content,
                    citations,
                  }
                : msg,
            ),
          );
        },
        onError: (message) => {
          setError(message);
          setChatStage(null);
          setLoading(false);
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId ? { ...msg, streaming: false, agentRunning: false } : msg,
            ),
          );
        },
      });
    } catch (err) {
      setError(String(err));
      if (assistantId) {
        setMessages((prev) => prev.filter((msg) => msg.id !== assistantId));
      }
    } finally {
      setChatStage(null);
      setLoading(false);
    }
  };

  const finishVoice = useCallback((message?: string) => {
    if (voiceDoneRef.current) return;
    voiceDoneRef.current = true;
    if (message) setError(message);
    setLoading(false);
    setVoiceStage(null);
  }, []);

  const sendVoice = async (blob: Blob) => {
    if (selectedDocIds.length === 0) {
      setError(t("chat.selectDocError"));
      return;
    }

    setLoading(true);
    setVoiceStage(t("voice.connecting"));
    setError(null);
    audioQueueRef.current = [];
    voiceDoneRef.current = false;

    let ws: WebSocket | null = null;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    const cleanup = (message?: string) => {
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

      timeoutId = setTimeout(() => {
        cleanup(t("voice.timeout"));
      }, 300_000);

      ws.onopen = () => {
        setVoiceStage(t("voice.transcribing"));
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

        if (payload.type === "status") {
          const stage = payload.stage as string;
          if (stage === "transcribing") setVoiceStage(t("voice.transcribing"));
          if (stage === "agent") setVoiceStage(t("chat.agentRunning"));
          if (stage === "answering") setVoiceStage(t("voice.generating"));
          if (stage === "speaking") setVoiceStage(t("voice.synthesizing"));
          return;
        }
        if (payload.type === "agent_step") {
          const step: AgentStepEvent = {
            step: payload.step as number,
            thought: (payload.thought as string) ?? "",
            action: (payload.action as string) ?? "",
            action_input: (payload.action_input as Record<string, unknown>) ?? {},
            observation: (payload.observation as string) ?? "",
            evidence_count: payload.evidence_count as number | undefined,
          };
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? { ...msg, agentSteps: [...(msg.agentSteps ?? []), step] }
                : msg,
            ),
          );
          return;
        }
        if (payload.type === "transcript") {
          setVoiceStage(t("chat.agentRunning"));
          const userMessageId = newId();
          scrollUserMessageIdRef.current = userMessageId;
          setMessages((prev) => [
            ...prev,
            { id: userMessageId, role: "user", content: payload.text as string },
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
        }
        if (payload.type === "citations") {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? { ...msg, citations: (payload.citations as ChatMessage["citations"]) ?? [] }
                : msg,
            ),
          );
        }
        if (payload.type === "answer_delta") {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? {
                    ...msg,
                    content: msg.content + (payload.content as string),
                    agentRunning: false,
                  }
                : msg,
            ),
          );
        }
        if (payload.type === "audio") {
          setVoiceStage(t("voice.playing"));
          enqueueAudio(payload.data as string);
        }
        if (payload.type === "done") {
          setSessionId(payload.session_id as string);
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? {
                    ...msg,
                    streaming: false,
                    agentRunning: false,
                    content: (payload.content as string | undefined) ?? msg.content,
                    citations: (payload.citations as ChatMessage["citations"]) ?? [],
                  }
                : msg,
            ),
          );
          cleanup();
        }
        if (payload.type === "error") {
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

  const openDocument = (target: ViewerTarget) => {
    const doc = documents.find((d) => d.id === target.documentId);
    setSidebarOpen(false);
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
  };

  const toggleSidebar = () => setSidebarOpen((prev) => !prev);

  const closeSidebarOnMobile = () => {
    if (window.innerWidth <= 900) setSidebarOpen(false);
  };

  const activeStage = voiceStage ?? chatStage;
  const hasMessages = messages.length > 0;

  const handleLocaleChange = (next: Locale) => {
    if (next !== locale) setLocale(next);
  };

  return (
    <div className={`app ${viewerTarget ? "with-viewer" : ""} ${viewerOpen ? "viewer-open" : ""}`}>
      <div
        className={`sidebar-overlay ${sidebarOpen ? "visible" : ""}`}
        onClick={() => setSidebarOpen(false)}
        aria-hidden="true"
      />

      <aside className={`sidebar ${sidebarOpen ? "open" : "collapsed"}`}>
        <div className="sidebar-inner">
          <div className="sidebar-top">
            <button className="icon-btn" onClick={toggleSidebar} aria-label={t("sidebar.collapse")}>
              <MenuIcon />
            </button>
          </div>

          <button className="new-chat-btn" onClick={clearChat}>
            <NewChatIcon />
            {t("sidebar.newChat")}
          </button>

          <label className="upload-btn">
            <input
              type="file"
              accept={UPLOAD_ACCEPT}
              hidden
              disabled={uploading}
              onChange={(e) => handleUpload(e.target.files?.[0] ?? null)}
            />
            <PlusIcon />
            <span>{uploading ? t("sidebar.uploading") : t("sidebar.uploadDoc")}</span>
          </label>
          <p className="upload-hint">{t("sidebar.uploadHint")}</p>

          <div className="sidebar-section-label">
            {t("sidebar.docLibrary", { count: readyDocs.length })}
          </div>

          <div className="doc-list">
            {documents.length === 0 && (
              <p className="doc-list-empty">{t("sidebar.emptyList")}</p>
            )}
            {documents.map((doc) => (
              <div key={doc.id} className={`doc-item ${doc.status}`}>
                <label className="doc-select">
                  <input
                    type="checkbox"
                    checked={selectedDocIds.includes(doc.id)}
                    disabled={doc.status !== "ready"}
                    onChange={() => toggleDoc(doc.id)}
                  />
                  <div className="doc-info">
                    <strong>{doc.name}</strong>
                    <div className="doc-meta">
                      <span className={`status ${doc.status}`}>{statusLabel[doc.status]}</span>
                      {doc.page_count ? (
                        <span className="muted">{t("doc.pages", { count: doc.page_count })}</span>
                      ) : null}
                      {doc.ocr_pages ? (
                        <span className="muted">OCR {doc.ocr_pages}</span>
                      ) : null}
                    </div>
                    {(doc.status === "pending" || doc.status === "processing") && (
                      <div className="index-progress">
                        <div className="index-progress-bar">
                          <div
                            className="index-progress-fill"
                            style={{ width: `${doc.status === "pending" ? 0 : doc.progress}%` }}
                          />
                        </div>
                        <span className="index-progress-label">
                          {doc.progress_message ??
                            (doc.status === "pending"
                              ? t("doc.status.pending")
                              : t("doc.indexing"))}
                          {doc.status === "processing" ? ` ${doc.progress}%` : ""}
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
                      className="doc-reindex"
                      onClick={() => handleReindex(doc.id)}
                      aria-label={t("sidebar.reindexDoc")}
                    >
                      <ReindexIcon />
                    </button>
                  )}
                  <button
                    className="doc-delete"
                    onClick={() => handleDelete(doc.id)}
                    disabled={doc.status === "deleting"}
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
              <DocIcon /> {t("topBar.docsSelected", { count: selectedDocIds.length })}
            </span>
          ) : (
            <span className="top-bar-sub top-bar-hint">
              {readyDocs.length === 0 ? t("topBar.uploadFirst") : t("topBar.selectDocs")}
            </span>
          )}
          <div className="lang-switch" role="group" aria-label={t("language.label")}>
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
            <section className="messages">
              {messages.map((msg) => (
                <article
                  key={msg.id}
                  className={`message ${msg.role}`}
                  ref={(el) => {
                    if (el) messageRefs.current.set(msg.id, el);
                    else messageRefs.current.delete(msg.id);
                  }}
                >
                  <div className="message-avatar">
                    {msg.role === "assistant" ? (
                      <AllDocsIcon size={28} />
                    ) : (
                      t("chat.userAvatar")
                    )}
                  </div>
                  <div className="message-body">
                    {msg.role === "assistant" &&
                    ((msg.agentSteps?.length ?? 0) > 0 || msg.agentRunning) ? (
                      <AgentSteps
                        steps={msg.agentSteps ?? []}
                        running={msg.agentRunning}
                      />
                    ) : null}
                    <div className="message-content">
                      {msg.role === "assistant" ? (
                        <MessageContent
                          content={msg.content}
                          citations={msg.citations ?? []}
                          onOpenDocument={openDocument}
                        />
                      ) : (
                        msg.content
                      )}
                      {msg.streaming ? <span className="cursor">▍</span> : null}
                    </div>
                  </div>
                </article>
              ))}
              <div ref={spacerRef} className="message-scroll-spacer" aria-hidden="true" />
            </section>
          )}
        </div>

        {(error || activeStage) && (
          <div className="status-bar">
            {error ? (
              <div className="banner error">{error}</div>
            ) : activeStage ? (
              <div className="status-pill">
                <span className="dot" />
                {activeStage}
              </div>
            ) : null}
          </div>
        )}

        <footer className="composer-wrap">
          <div className="input-pill">
            <textarea
              ref={textareaRef}
              value={input}
              placeholder={t("chat.placeholder")}
              rows={1}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  sendText();
                }
              }}
            />
            <div className="input-actions">
              <button
                className={`action-btn mic ${recording ? "active" : ""}`}
                onClick={recording ? stopRecording : startRecording}
                disabled={loading && !recording}
                title={t("voice.ask")}
                aria-label={recording ? t("voice.stopRecording") : t("voice.ask")}
              >
                <MicIcon />
              </button>
              <button
                className="action-btn send"
                onClick={() => sendText()}
                disabled={loading || !input.trim()}
                title={t("composer.send")}
                aria-label={t("composer.send")}
              >
                <SendIcon />
              </button>
            </div>
          </div>
          <p className="composer-disclaimer">{t("app.disclaimer")}</p>
        </footer>
      </div>

      {viewerTarget && (
        <div className={`doc-viewer-slot ${viewerOpen ? "is-open" : ""}`}>
          <DocumentViewer
            key={`${viewerTarget.documentId}-${viewerTarget.page ?? 1}`}
            target={viewerTarget}
            onClose={closeViewer}
          />
        </div>
      )}
    </div>
  );
}
