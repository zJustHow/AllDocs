import type { AgentStepEvent, Citation, DocumentItem, MessageEmbed } from "./types";
import { t } from "./i18n";

const API_BASE = "";

export async function listDocuments(): Promise<DocumentItem[]> {
  const res = await fetch(`${API_BASE}/api/v1/documents`);
  if (!res.ok) throw new Error(t("errors.loadDocumentsFailed"));
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
    throw new Error(detail || t("errors.uploadFailed"));
  }
  return res.json();
}

export async function deleteDocument(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(t("errors.deleteFailed"));
}

export async function reindexDocument(id: string): Promise<DocumentItem> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${id}/reindex`, { method: "POST" });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || t("errors.reindexFailed"));
  }
  return res.json();
}

export async function getDocumentFileUrl(documentId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${documentId}/file`);
  if (!res.ok) throw new Error(t("errors.loadDocumentFailed"));
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export interface StreamHandlers {
  onStatus?: (stage: string) => void;
  onAgentStep?: (step: AgentStepEvent) => void;
  onCitations?: (citations: Citation[]) => void;
  onEmbeds?: (embeds: MessageEmbed[]) => void;
  onDelta: (text: string) => void;
  onDone: (payload: {
    sessionId: string;
    content?: string;
    citations: Citation[];
    embeds: MessageEmbed[];
    language: string;
  }) => void;
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
    throw new Error(t("errors.chatRequestFailed"));
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
      if (payload.type === "agent_step") {
        handlers.onAgentStep?.({
          step: payload.step as number,
          thought: (payload.thought as string) ?? "",
          action: (payload.action as string) ?? "",
          action_input: (payload.action_input as Record<string, unknown>) ?? {},
          observation: (payload.observation as string) ?? "",
          evidence_count: payload.evidence_count as number | undefined,
        });
      }
      if (payload.type === "citations") {
        handlers.onCitations?.((payload.citations as Citation[]) ?? []);
      }
      if (payload.type === "embeds") {
        handlers.onEmbeds?.((payload.embeds as MessageEmbed[]) ?? []);
      }
      if (payload.type === "delta") handlers.onDelta(payload.content as string);
      if (payload.type === "done") {
        finished = true;
        handlers.onDone({
          sessionId: payload.session_id as string,
          content: payload.content as string | undefined,
          citations: (payload.citations as Citation[]) ?? [],
          embeds: (payload.embeds as MessageEmbed[]) ?? [],
          language: payload.language as string,
        });
      }
      if (payload.type === "error") {
        finished = true;
        handlers.onError((payload.message as string) ?? t("errors.chatFailed"));
      }
    }
  }

  if (!finished) {
    handlers.onError(t("errors.chatIncomplete"));
  }
}

export function createVoiceSocket(): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return new WebSocket(`${protocol}//${window.location.host}/ws/voice`);
}
