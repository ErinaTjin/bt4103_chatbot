// Based on Python backend models
// May need to change the variable name based on backend

export type Intent = 
  | "distribution"
  | "trend" 
  | "topN"
  | "comparison"
  | "unsupported";

export interface Filter {
  field: string;
  op: string;
  value: string | number;
}

export interface QueryPlan {
  intent: Intent;
  metric: string;
  dimensions: string[];
  filters: Filter[];
  limit: number;
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
  guardrails: Guardrails;
  warnings?: string[];
  error?: string;
}

export type Message = {
  id: string;
  content: string;
  result?: QueryResponse;
  timestamp: Date;
};

// Helper type for table rows
export type DataRow = Record<string, string | number>;