export interface DocumentItem {
  id: string;
  name: string;
  status: "pending" | "processing" | "ready" | "failed";
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

export interface AgentPlannerHint {
  intent?: string;
  symptom?: string | null;
  apply_metadata_filters?: boolean;
  filters?: Record<string, unknown> | null;
  sub_queries?: Array<{
    slot: string;
    query: string;
    content_roles?: string[] | null;
    chunk_types?: string[] | null;
  }>;
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
  agentPlannerHint?: AgentPlannerHint | null;
  agentRunning?: boolean;
}
