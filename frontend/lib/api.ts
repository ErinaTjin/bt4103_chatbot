import { QueryResponse } from './types';

const BACKEND_URL = 'http://localhost:8000';

// API wrapper for backend communication
export async function queryBackend(message: string): Promise<QueryResponse> {
  console.log('[API] Sending query:', message);

  const response = await fetch(`${BACKEND_URL}/nl2sql/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: message }),
  });

  if (!response.ok) {
    console.error('[API] Backend error:', response.status, response.statusText);
    throw new Error(`Backend error: ${response.status}`);
  }

  const raw = await response.json();

  // Reshape backend response to match frontend QueryResponse type
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
    error: raw.error || (raw.executed === false && !raw.warnings?.length)
      ? 'Failed to execute query'
      : undefined,
  };
}
