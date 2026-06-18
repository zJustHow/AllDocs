export interface DocumentItem {
  id: string;
  name: string;
  content_type?: string;
  status: "pending" | "processing" | "ready" | "failed" | "deleting";
  page_count: number | null;
  ocr_pages: number | null;
  progress: number;
  progress_message: string | null;
  error_message: string | null;
  created_at: string;
}

export interface Citation {
  document_id: string;
  document_name: string;
  page: number | null;
  section: string | null;
  snippet: string;
  score?: number | null;
  bbox?: number[] | null;
}

export interface MessageEmbed {
  ref: number;
  block_index?: number | null;
  asset_id?: string | null;
  content_hash?: string | null;
  document_id: string;
  document_name?: string | null;
  page: number;
  type: "table" | "figure" | "page" | string;
  url: string;
  bbox?: number[] | null;
  caption?: string | null;
}

export interface AgentStepEvent {
  step: number;
  thought: string;
  reasoning?: string;
  action: string;
  action_input: Record<string, unknown>;
  observation: string;
  evidence_count?: number;
  status?: "running" | "done";
}

export interface AgentThoughtDelta {
  step: number;
  field: "reasoning" | "content";
  delta: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  embeds?: MessageEmbed[];
  streaming?: boolean;
  agentSteps?: AgentStepEvent[];
  agentRunning?: boolean;
}
