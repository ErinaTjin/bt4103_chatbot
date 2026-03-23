import { Message, QueryResponse } from './types';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

function toHistory(messages: Message[]) {
  return messages.map((m) => ({
    role: m.role,
    content: m.content,
    timestamp: m.timestamp,
    kind: m.kind,
  }));
}

// API wrapper for backend communication
export async function queryBackend(message: string, messages: Message[] = [], mode: "fast" | "strict" = "fast"): Promise<QueryResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 200000); // 200s for slow local LLM

  const response = await fetch(`${BACKEND_URL}/nl2sql/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: message,
      conversation_history: toHistory(messages),
      mode,
    }),
    signal: controller.signal,
  });
  clearTimeout(timeoutId);

  if (!response.ok) {
    throw new Error(`Backend error: ${response.status}`);
  }

  const raw = await response.json();

  return {
    data: raw.data?.rows ?? [],
    sql: raw.sql ?? '',
    query_plan: raw.plan ?? {},
    plan_agent1: raw.plan_agent1,
    plan_agent2: raw.plan_agent2,
    guardrails: {
      ok: raw.warnings?.length === 0,
      warnings: raw.warnings ?? [],
    },
    warnings: raw.warnings ?? [],
    metadata: raw.metadata ?? undefined,
    error:
      raw.error || ((raw.executed === false && (!raw.warnings || raw.warnings.length === 0))
        ? 'Failed to execute query'
        : undefined),
  };
}
