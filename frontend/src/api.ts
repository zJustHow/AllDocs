import type { Citation, DocumentItem } from "./types";

const API_BASE = "";

export async function listDocuments(): Promise<DocumentItem[]> {
  const res = await fetch(`${API_BASE}/api/v1/documents`);
  if (!res.ok) throw new Error("Failed to load documents");
  return res.json();
}

export async function uploadDocument(file: File): Promise<DocumentItem> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/v1/documents`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Upload failed");
  }
  return res.json();
}

export async function deleteDocument(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Delete failed");
}

export async function getDocumentFileUrl(documentId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${documentId}/file`);
  if (!res.ok) throw new Error("无法加载文档");
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export interface StreamHandlers {
  onStatus?: (stage: string) => void;
  onCitations?: (citations: Citation[]) => void;
  onDelta: (text: string) => void;
  onDone: (payload: { sessionId: string; citations: Citation[]; language: string }) => void;
  onError: (message: string) => void;
}

export async function streamChat(
  message: string,
  sessionId: string | null,
  docIds: string[],
  handlers: StreamHandlers,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      doc_ids: docIds,
      stream: true,
    }),
  });

  if (!res.ok || !res.body) {
    throw new Error("Chat request failed");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      let payload: { type: string; [key: string]: unknown };
      try {
        payload = JSON.parse(line.slice(6));
      } catch {
        continue;
      }
      if (payload.type === "status") handlers.onStatus?.(payload.stage as string);
      if (payload.type === "citations") {
        handlers.onCitations?.((payload.citations as Citation[]) ?? []);
      }
      if (payload.type === "delta") handlers.onDelta(payload.content as string);
      if (payload.type === "done") {
        finished = true;
        handlers.onDone({
          sessionId: payload.session_id as string,
          citations: (payload.citations as Citation[]) ?? [],
          language: payload.language as string,
        });
      }
      if (payload.type === "error") {
        finished = true;
        handlers.onError((payload.message as string) ?? "Chat failed");
      }
    }
  }

  if (!finished) {
    handlers.onError("回答未完成，请重试");
  }
}

export function createVoiceSocket(): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return new WebSocket(`${protocol}//${window.location.host}/ws/voice`);
}
