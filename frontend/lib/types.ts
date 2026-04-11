// Based on Python backend models
// May need to change the variable name based on backend
 
export type Intent =
  | "count"
  | "distribution"
  | "trend"
  | "topN"
  | "mutation_prevalence"
  | "cohort_comparison"
  | "unsupported";
 
export interface Filter {
  field: string;
  op: string;
  value: string | number | (string | number)[];
}
 
export interface OutputPrefs {
  preferred_visualization?: "bar" | "line" | "pie" | "metric" | "table" | string | null;
}
 
export interface QueryPlan {
  intent: Intent;
  metric: string;
  dimensions: string[];
  filters: Filter[];
  limit: number;
  output?: OutputPrefs;
  needs_clarification: boolean;
  clarification_question: string | null;
  intent_summary?: string;
  reasoning_summary?: string;
}
 
export interface Guardrails {
  ok: boolean;
  warnings: string[];
}
 
export interface QueryResponse {
  data: Record<string, string | number>[];
  sql: string;
  query_plan: QueryPlan;
  plan_agent0?: Context;
  plan_agent1?: QueryPlan;
  plan_agent2?: QueryPlan;
  guardrails: Guardrails;
  warnings?: string[];
  metadata?: Record<string, unknown>;
  error?: string;
  resolved_question?: string;
  active_filters?: Record<string, unknown>;
}
 
export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  result?: QueryResponse;
  timestamp: string;
  kind?: "query" | "clarification" | "result" | "error";
};
 
// Helper type for table rows
export type DataRow = Record<string, string | number>;
 
// Past conversations / history
export interface Conversation {
  id: number;
  title: string;
  created_at: string;
}
 
export interface ConversationMessage {
  id: number;
  conversation_id: number;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}
 
// Admin user entry from /admin/users
export interface AdminUser {
  id: number;
  username: string;
  role: "admin" | "user";
  created_at: string;
}

// Admin audit log entry from /admin/logs
export interface AuditLog {
  id: number;
  timestamp: string;
  username: string | null;
  session_id: string | null;
  nl_question: string | null;
  resolved_question: string | null;
  generated_sql: string | null;
  execution_ms: number | null;
  row_count: number | null;
  guardrail_decision: string;
  guardrail_reasons: string; // JSON-encoded string[]
  warnings: string;          // JSON-encoded string[]
  error_message: string | null;
  result_preview: string | null; // JSON-encoded first 10 result rows
}
 
// Auth event log entry from /admin/auth-logs
export interface AuthLog {
  id: number;
  timestamp: string;
  event: string;
  actor: string | null;
  target: string | null;
  success: number; // 1 = success, 0 = failure
  detail: string | null;
}

// Request body for /nl2sql/chat endpoint (shape of response frontend expects from backend /nl2sql/chat)
export interface ChatResponse extends QueryResponse {
  session_id: string;
  resolved_question: string;
  active_filters: Record<string, unknown>;
  chat_history: { role: string; content: string }[];
}