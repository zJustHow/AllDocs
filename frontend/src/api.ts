import type {
  AgentStepEvent,
  AgentThoughtDelta,
  Citation,
  DocumentItem,
  MessageEmbed,
} from "./types";
import { parseAgentStepPayload } from "./agentStepUtils";
import { authFetch, authFetchJson } from "./auth/http";
import { getAccessToken, withAuthQuery } from "./auth/tokenStore";
import { t } from "./i18n";

const API_BASE = "";

export function documentFileUrl(documentId: string): string {
  return withAuthQuery(`${API_BASE}/api/v1/documents/${documentId}/file`);
}

export function documentPreviewUrl(documentId: string): string {
  return withAuthQuery(`${API_BASE}/api/v1/documents/${documentId}/preview`);
}

export function documentPageRenderUrl(
  documentId: string,
  page: number,
  scale = 2,
): string {
  return withAuthQuery(
    `${API_BASE}/api/v1/documents/${documentId}/pages/${page}/render?scale=${scale}`,
  );
}

export function assetUrl(assetId: string): string {
  return withAuthQuery(`${API_BASE}/api/v1/assets/${assetId}`);
}

export async function listDocuments(): Promise<DocumentItem[]> {
  return authFetchJson<DocumentItem[]>("/api/v1/documents");
}

export async function uploadDocument(file: File): Promise<DocumentItem> {
  const form = new FormData();
  form.append("file", file);
  const res = await authFetch("/api/v1/documents", {
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
  const res = await authFetch(`/api/v1/documents/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(t("errors.deleteFailed"));
}

export async function reindexDocument(id: string): Promise<DocumentItem> {
  const res = await authFetch(`/api/v1/documents/${id}/reindex`, { method: "POST" });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || t("errors.reindexFailed"));
  }
  return res.json();
}

export async function setDocumentChatEnabled(
  id: string,
  chatEnabled: boolean,
): Promise<DocumentItem> {
  const res = await authFetch(`/api/v1/documents/${id}/chat-enabled`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_enabled: chatEnabled }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || t("errors.updateDocFailed"));
  }
  return res.json();
}

export interface StreamHandlers {
  onStatus?: (stage: string) => void;
  onAgentStep?: (step: AgentStepEvent) => void;
  onAgentThoughtDelta?: (delta: AgentThoughtDelta) => void;
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
  const res = await authFetch("/api/v1/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      doc_ids: docIds,
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
      if (payload.type === "agent_thought_delta") {
        handlers.onAgentThoughtDelta?.({
          step: payload.step as number,
          field: (payload.field as AgentThoughtDelta["field"]) ?? "content",
          delta: (payload.delta as string) ?? "",
        });
      }
      const agentStep = parseAgentStepPayload(payload);
      if (agentStep) handlers.onAgentStep?.(agentStep);
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
  const token = getAccessToken();
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  return new WebSocket(`${protocol}//${window.location.host}/ws/voice${query}`);
}

export type SettingFieldType = "string" | "int" | "float" | "bool" | "secret";

export interface SettingField {
  key: string;
  type: SettingFieldType;
  secret: boolean;
  default: string | number | boolean;
  overridden: boolean;
  value: string | number | boolean | null;
  masked?: string | null;
  set?: boolean;
}

export interface SettingsGroup {
  id: string;
  fields: SettingField[];
}

export interface SettingsPayload {
  groups: SettingsGroup[];
}

export async function fetchSettings(): Promise<SettingsPayload> {
  return authFetchJson<SettingsPayload>("/api/v1/settings");
}

export async function patchSettings(
  values: Record<string, string | number | boolean | null>,
): Promise<SettingsPayload> {
  const res = await authFetch("/api/v1/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || t("errors.saveSettingsFailed"));
  }
  return res.json();
}
