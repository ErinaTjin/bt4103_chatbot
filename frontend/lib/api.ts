import { QueryResponse, Conversation, ConversationMessage, AuditLog } from './types';
import { getAuthHeader } from './auth';
 
const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

function handleUnauthorized(status: number): void { //handle 401 errors globally to auto-logout users with expired tokens
  if (status === 401) {
    sessionStorage.removeItem("auth_user");
    window.location.replace("/login");
  }
}

// ── NL2SQL chat ───────────────────────────────────────────────────────────────
export async function queryBackend(
  message: string,
  sessionId: string,
  conversationId: number,
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
      conversation_id: conversationId,
      question: message,
      mode,
      conversation_history: conversationHistory,
    }),
    signal: controller.signal,
  });
  clearTimeout(timeoutId);
 
  if (!response.ok) {
    handleUnauthorized(response.status);
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
    plan_agent0: raw.plan_agent0,
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
 
export async function resetSession(convId: number): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/session/${convId}/reset`, {
    method: "DELETE",
    headers: { ...getAuthHeader() },
  });
  if (!res.ok) handleUnauthorized(res.status);
}
 
export async function clearSessionFilters(convId: number): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/session/${convId}/filters`, {
    method: "PATCH",
    headers: { ...getAuthHeader() },
  });
  if (!res.ok) handleUnauthorized(res.status);
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

export async function deleteConversation(convId: number): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/conversations/${convId}`, {
    method: 'DELETE',
    headers: { ...getAuthHeader() },
  });
  if (!res.ok) {
    handleUnauthorized(res.status);
    throw new Error(`Failed to delete conversation: ${res.status}`);
  }
}

// ── Admin ─────────────────────────────────────────────────────────────────────

export async function getAdminLogs(limit = 200, offset = 0): Promise<AuditLog[]> {
  const res = await fetch(
    `${BACKEND_URL}/admin/logs?limit=${limit}&offset=${offset}`,
    { headers: { 'Content-Type': 'application/json', ...getAuthHeader() } },
  );
  if (!res.ok) {
    handleUnauthorized(res.status);
    throw new Error(`Failed to fetch audit logs: ${res.status}`);
  }
  return res.json();
}