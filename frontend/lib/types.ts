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