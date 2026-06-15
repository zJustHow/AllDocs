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

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  streaming?: boolean;
}
