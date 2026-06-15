import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createVoiceSocket,
  deleteDocument,
  listDocuments,
  streamChat,
  uploadDocument,
} from "./api";
import { citationToViewerTarget, type ViewerTarget } from "./citations";
import DocumentViewer from "./DocumentViewer";
import MessageContent from "./MessageContent";
import type { ChatMessage, DocumentItem } from "./types";

const STATUS_LABEL: Record<DocumentItem["status"], string> = {
  pending: "等待处理",
  processing: "索引中",
  ready: "可用",
  failed: "失败",
};

function newId() {
  return crypto.randomUUID();
}

export default function App() {
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

  const messagesRef = useRef<HTMLElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioQueueRef = useRef<HTMLAudioElement[]>([]);
  const playingRef = useRef(false);
  const voiceDoneRef = useRef(false);

  const readyDocs = useMemo(
    () => documents.filter((doc) => doc.status === "ready"),
    [documents],
  );

  const indexingDocs = useMemo(
    () => documents.filter((doc) => doc.status === "pending" || doc.status === "processing"),
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
    const intervalMs = indexingDocs.length > 0 ? 1500 : 5000;
    const timer = setInterval(() => {
      refreshDocuments().catch(() => undefined);
    }, intervalMs);
    return () => clearInterval(timer);
  }, [refreshDocuments, indexingDocs.length]);

  useEffect(() => {
    const container = messagesRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [messages, loading]);

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
    if (!confirm("确定删除该文档？")) return;
    await deleteDocument(docId);
    await refreshDocuments();
  };

  const sendText = async () => {
    const text = input.trim();
    if (!text || loading) return;
    if (selectedDocIds.length === 0) {
      setError("请至少选择一份已就绪的说明书");
      return;
    }

    setError(null);
    setInput("");
    setLoading(true);
    setChatStage("思考中...");

    const userMessage: ChatMessage = { id: newId(), role: "user", content: text };
    const assistantId = newId();
    setMessages((prev) => [
      ...prev,
      userMessage,
      { id: assistantId, role: "assistant", content: "", streaming: true },
    ]);

    try {
      await streamChat(text, sessionId, selectedDocIds, {
        onStatus: (stage) => {
          if (stage === "retrieving") setChatStage("检索文档...");
        },
        onCitations: (citations) => {
          setMessages((prev) =>
            prev.map((msg) => (msg.id === assistantId ? { ...msg, citations } : msg)),
          );
        },
        onDelta: (delta) => {
          setChatStage("生成回答...");
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId ? { ...msg, content: msg.content + delta } : msg,
            ),
          );
        },
        onDone: ({ sessionId: sid, citations }) => {
          setSessionId(sid);
          setChatStage(null);
          setLoading(false);
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? { ...msg, streaming: false, citations }
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
              msg.id === assistantId ? { ...msg, streaming: false } : msg,
            ),
          );
        },
      });
    } catch (err) {
      setError(String(err));
      setMessages((prev) => prev.filter((msg) => msg.id !== assistantId));
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
      setError("请至少选择一份已就绪的说明书");
      return;
    }

    setLoading(true);
    setVoiceStage("连接中...");
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
        cleanup("语音处理超时，请重试");
      }, 300_000);

      ws.onopen = () => {
        setVoiceStage("识别语音...");
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
          cleanup("语音响应解析失败");
          return;
        }

        if (payload.type === "status") {
          const stage = payload.stage as string;
          if (stage === "transcribing") setVoiceStage("识别语音...");
          if (stage === "answering") setVoiceStage("生成回答...");
          if (stage === "speaking") setVoiceStage("合成语音...");
          return;
        }
        if (payload.type === "transcript") {
          setVoiceStage("生成回答...");
          setMessages((prev) => [
            ...prev,
            { id: newId(), role: "user", content: payload.text as string },
            { id: assistantId, role: "assistant", content: "", streaming: true, citations: [] },
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
                ? { ...msg, content: msg.content + (payload.content as string) }
                : msg,
            ),
          );
        }
        if (payload.type === "audio") {
          setVoiceStage("播放语音...");
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
        cleanup("语音连接失败");
      };

      ws.onclose = () => {
        if (!voiceDoneRef.current) {
          cleanup("语音连接已断开");
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

  const openDocument = (target: ViewerTarget) => setViewerTarget(target);

  return (
    <div className={`app ${viewerTarget ? "with-viewer" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <h1>AllDocs</h1>
          <p>说明书 RAG 问答 · 本地语音</p>
        </div>

        <label className="upload-box">
          <input
            type="file"
            accept="application/pdf"
            hidden
            onChange={(e) => handleUpload(e.target.files?.[0] ?? null)}
          />
          <span>{uploading ? "上传中..." : "上传 PDF 说明书"}</span>
        </label>

        <div className="doc-list">
          <h2>文档库</h2>
          {documents.length === 0 && <p className="muted">暂无文档</p>}
          {documents.map((doc) => (
            <div key={doc.id} className={`doc-item ${doc.status}`}>
              <label className="doc-select">
                <input
                  type="checkbox"
                  checked={selectedDocIds.includes(doc.id)}
                  disabled={doc.status !== "ready"}
                  onChange={() => toggleDoc(doc.id)}
                />
                <div>
                  <strong>{doc.name}</strong>
                  <span className={`status ${doc.status}`}>{STATUS_LABEL[doc.status]}</span>
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
                          (doc.status === "pending" ? "等待处理" : "索引中...")}
                        {doc.status === "processing" ? ` ${doc.progress}%` : ""}
                      </span>
                    </div>
                  )}
                  {doc.page_count ? <span className="muted">{doc.page_count} 页</span> : null}
                  {doc.ocr_pages ? <span className="muted">OCR {doc.ocr_pages} 页</span> : null}
                  {doc.error_message ? <span className="error-text">{doc.error_message}</span> : null}
                </div>
              </label>
              <button className="ghost" onClick={() => handleDelete(doc.id)}>
                删除
              </button>
            </div>
          ))}
        </div>

        <div className="sidebar-foot">
          <span>{readyDocs.length} 份可用</span>
          <span>LLM: DeepSeek API</span>
        </div>
      </aside>

      <main className="chat">
        <header className="chat-header">
          <h2>问答</h2>
          <p>支持中文 / 英文提问</p>
        </header>

        <section className="messages" ref={messagesRef}>
          {messages.length === 0 && (
            <div className="empty">
              <h3>开始提问</h3>
              <p>例如：「报警 E-204 怎么处理？」或 “How do I power on the device?”</p>
            </div>
          )}
          {messages.map((msg) => (
            <article key={msg.id} className={`bubble ${msg.role}`}>
              <div className="bubble-meta">{msg.role === "user" ? "你" : "助手"}</div>
              <div className="bubble-content">
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
            </article>
          ))}
        </section>

        {error && <div className="banner error">{error}</div>}

        <footer className="composer">
          <textarea
            value={input}
            placeholder="输入问题，或按住麦克风语音提问..."
            rows={2}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendText();
              }
            }}
          />
          <div className="composer-actions">
            <button
              className={`mic ${recording ? "active" : ""}`}
              onClick={recording ? stopRecording : startRecording}
              disabled={loading && !recording}
              title="语音提问"
            >
              {recording ? "停止" : "语音"}
            </button>
            <button className="primary" onClick={sendText} disabled={loading || !input.trim()}>
              {voiceStage ?? chatStage ?? (loading ? "处理中..." : "发送")}
            </button>
          </div>
        </footer>
      </main>

      {viewerTarget && (
        <DocumentViewer target={viewerTarget} onClose={() => setViewerTarget(null)} />
      )}
    </div>
  );
}
