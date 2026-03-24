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
}

export interface Guardrails {
  ok: boolean;
  warnings: string[];
}

export interface QueryResponse {
  data: Record<string, string | number>[];
  sql: string;
  query_plan: QueryPlan;
  plan_agent1?: QueryPlan;
  plan_agent2?: QueryPlan;
  guardrails: Guardrails;
  warnings?: string[];
  metadata?: Record<string, unknown>;
  error?: string;
  resolved_question?: string;
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

// Request body for /nl2sql/chat endpoint (shape of response frontend expects from backend /nl2sql/chat)
export interface ChatResponse extends QueryResponse {
  session_id: string;
  resolved_question: string;
  active_filters: Record<string, unknown>;
  chat_history: { role: string; content: string }[];
}