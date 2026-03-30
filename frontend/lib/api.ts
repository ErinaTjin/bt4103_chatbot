import { QueryResponse, Conversation, ConversationMessage } from './types';
import { getAuthHeader } from './auth';
 
const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
 
// ── NL2SQL chat ───────────────────────────────────────────────────────────────
export async function queryBackend(
  message: string,
  sessionId: string,
  mode: "fast" | "strict" = "fast",
  conversationHistory: Array<{ role: string; content: string; kind?: string }> = [],
): Promise<QueryResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 400000);
 
  const response = await fetch(`${BACKEND_URL}/nl2sql/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify({
      session_id: sessionId,
      question: message,
      mode,
      conversation_history: conversationHistory,
    }),
    signal: controller.signal,
  });
  clearTimeout(timeoutId);
 
  if (!response.ok) {
    console.error('[API] Backend error:', response.status, response.statusText);
    throw new Error(`Backend error: ${response.status}`);
  }
 
  const raw = await response.json();
  return {
    data: raw.data?.rows ?? [],
    sql: raw.sql ?? '',
    query_plan: {
      ...(raw.plan ?? {}),
      output: {
        preferred_visualization:
          raw.plan?.output?.preferred_visualization ?? raw.plan?.preferred_visualization ?? null,
      },
    },
    plan_agent1: raw.plan_agent1,
    plan_agent2: raw.plan_agent2,
    guardrails: { ok: raw.warnings?.length === 0, warnings: raw.warnings ?? [] },
    warnings: raw.warnings ?? [],
    resolved_question: raw.resolved_question ?? undefined,
    error:
      raw.error ||
      (raw.executed === false && !raw.warnings?.length ? 'Failed to execute query' : undefined),
  };
}
 
// ── Session (now user-keyed, requires auth) ───────────────────────────────────
 
export async function resetSession(): Promise<void> {
  await fetch(`${BACKEND_URL}/session/reset`, {
    method: "DELETE",
    headers: { ...getAuthHeader() },
  });
}
 
export async function clearSessionFilters(): Promise<void> {
  await fetch(`${BACKEND_URL}/session/filters`, {
    method: "PATCH",
    headers: { ...getAuthHeader() },
  });
}
 
// ── Conversations ─────────────────────────────────────────────────────────────
 
export async function getConversations(): Promise<Conversation[]> {
  const res = await fetch(`${BACKEND_URL}/conversations`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
  });
  if (!res.ok) throw new Error(`Failed to fetch conversations: ${res.status}`);
  return res.json();
}
 
export async function createConversation(): Promise<{ id: number }> {
  const res = await fetch(`${BACKEND_URL}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
  });
  if (!res.ok) throw new Error(`Failed to create conversation: ${res.status}`);
  return res.json();
}
 
export async function getConversationMessages(id: number): Promise<ConversationMessage[]> {
  const res = await fetch(`${BACKEND_URL}/conversations/${id}/messages`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
  });
  if (!res.ok) throw new Error(`Failed to fetch messages: ${res.status}`);
  return res.json();
}
 
export async function appendMessage(
  convId: number,
  role: 'user' | 'assistant',
  content: string,
): Promise<ConversationMessage> {
  const res = await fetch(`${BACKEND_URL}/conversations/${convId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
    body: JSON.stringify({ role, content }),
  });
  if (!res.ok) throw new Error(`Failed to append message: ${res.status}`);
  return res.json();
}