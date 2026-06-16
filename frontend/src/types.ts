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
}

export interface AgentStepEvent {
  step: number;
  thought: string;
  action: string;
  action_input: Record<string, unknown>;
  observation: string;
  evidence_count?: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  streaming?: boolean;
  agentSteps?: AgentStepEvent[];
  agentRunning?: boolean;
}
