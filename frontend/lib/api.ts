import { QueryResponse } from './types';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

// API wrapper for backend communication
export async function queryBackend(
  message: string,
  sessionId: string,
  mode: "fast" | "strict" = "fast"
): Promise<QueryResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 200000); // 200s for slow local LLM

  const response = await fetch(`${BACKEND_URL}/nl2sql/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, question: message, mode }),
    signal: controller.signal,
  });
  clearTimeout(timeoutId);

  if (!response.ok) throw new Error(`Backend error: ${response.status}`);

  const raw = await response.json();
  return {
    data: raw.data?.rows ?? [],
    sql: raw.sql ?? "",
    query_plan: raw.plan ?? {},
    plan_agent1: raw.plan_agent1,
    plan_agent2: raw.plan_agent2,
    guardrails: { ok: raw.warnings?.length === 0, warnings: raw.warnings ?? [] },
    warnings: raw.warnings ?? [],
    resolved_question: raw.resolved_question ?? undefined,
    error: raw.error || (raw.executed === false && !raw.warnings?.length
      ? "Failed to execute query" : undefined),
  };
}

export async function resetSession(sessionId: string): Promise<void> {
  await fetch(`${BACKEND_URL}/session/${sessionId}`, { method: "DELETE" });
}

export async function clearSessionFilters(sessionId: string): Promise<void> {
  await fetch(`${BACKEND_URL}/session/${sessionId}/filters`, { method: "PATCH" });
}