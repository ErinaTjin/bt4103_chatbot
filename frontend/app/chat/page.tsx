"use client";
 
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Conversation, Message } from "@/lib/types";
import {
  queryBackend,
  resetSession,
  clearSessionFilters,
  getConversations,
  createConversation,
  getConversationMessages,
  appendMessage,
  deleteConversation,
} from "@/lib/api";
import { MessageBubble } from "@/components/MessageBubble";
import { ChatInput } from "@/components/ChatInput";
import { useAuth } from "@/context/AuthContext";
import {
  ChevronLeft,
  ChevronRight,
  LogOut,
  MessageSquare,
  Plus,
  Bug,
  RotateCcw,
  ShieldAlert,
  Trash2,
  CheckCircle2,
} from "lucide-react";
 
// Per-tab unique ID used only for audit log tracing — not for session state
const SESSION_KEY = "anchor_session_id";
 
const WELCOME_MESSAGE: Message = {
  id: "welcome",
  role: "assistant",
  content: "Hello! Ask me anything about the cancer data.",
  timestamp: new Date().toISOString(),
  kind: "result",
};
 
export default function ChatPage() {
  const router = useRouter();
  const { user, isAdmin, loading, logout } = useAuth();
 
  // ── All useState declarations first ─────────────────────────────────────
 
  // Per-conversation message store: Map<convId | "new", Message[]>
  // Using a Map means switching conversations never wipes another conversation's messages.
  // "new" key is used before a conversation is created in the DB.
  const [convMessages, setConvMessages] = useState<
    Map<number | "new", Message[]>
  >(() => new Map([["new", [WELCOME_MESSAGE]]]));
 
  const [sessionId, setSessionId] = useState<string>("");
 
  // Track loading per conversation so switching chats doesn't show dots
  // in the wrong conversation and doesn't disable the input globally.
  const [loadingConvIds, setLoadingConvIds] = useState<Set<number | "new">>(
    new Set(),
  );
 
  // Active filters from the most recent query response — per conversation
  const [convActiveFilters, setConvActiveFilters] = useState<
    Map<number | "new", Record<string, unknown>>
  >(new Map());
 
  const [debugMode, setDebugMode] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return sessionStorage.getItem("anchor_debug_mode") === "true";
  });
  const [chatMode, setChatMode] = useState<"fast" | "strict">("fast");
 
  // Sidebar
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [sidebarLoading, setSidebarLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [showResetToast, setShowResetToast] = useState(false);
 
  // ── All useRef declarations ───────────────────────────────────────────────
 
  // Ref so handleSend always sees current conv ID without stale closure
  const activeConvIdRef = useRef<number | null>(null);
 
  // Abort controller for the current in-flight query — allows user to stop it
  const abortControllerRef = useRef<AbortController | null>(null);
  const stoppedByUserRef = useRef<boolean>(false);
 
  // ── Derived values (must be after all useState/useRef above) ─────────────
 
  // Derived: messages for the currently viewed conversation
  // Must be after activeConvId is declared
  const messages = convMessages.get(activeConvId ?? "new") ?? [WELCOME_MESSAGE];
 
  // Derived: active filters for the currently viewed conversation
  const activeFilters = convActiveFilters.get(activeConvId ?? "new") ?? {};
 
  // Derived: is the currently viewed conversation loading?
  // Must be after activeConvId and loadingConvIds are declared
  const activeKey = activeConvId ?? "new";
  const isLoading = loadingConvIds.has(activeKey);
 
  // ── Helpers (must be after all state above) ───────────────────────────────
 
  // Update messages for one conversation without touching others
  const setMessagesForConv = (
    convKey: number | "new",
    updater: Message[] | ((prev: Message[]) => Message[]),
  ) => {
    setConvMessages((prev) => {
      const next = new Map(prev);
      const current = next.get(convKey) ?? [WELCOME_MESSAGE];
      next.set(
        convKey,
        typeof updater === "function" ? updater(current) : updater,
      );
      return next;
    });
  };
 
  const setConvLoading = (key: number | "new", loading: boolean) => {
    setLoadingConvIds((prev) => {
      const next = new Set(prev);
      if (loading) next.add(key);
      else next.delete(key);
      return next;
    });
  };
 
  // ── Session ID (audit tracing only) ──────────────────────────────────────
  useEffect(() => {
    let id = sessionStorage.getItem(SESSION_KEY);
    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem(SESSION_KEY, id);
    }
    setSessionId(id);
  }, []);
 
  // ── Persist debug mode ────────────────────────────────────────────────────
  useEffect(() => {
    sessionStorage.setItem("anchor_debug_mode", String(debugMode));
  }, [debugMode]);
 
  // ── Redirect if not authenticated ─────────────────────────────────────────
  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);
 
  // ── Load sidebar + restore all conversations on login ───────────────────
  useEffect(() => {
    if (!user) return;
    setSidebarLoading(true);
    getConversations()
      .then(async (convs) => {
        setConversations(convs);
        if (convs.length === 0) return;
 
        // Load messages for ALL conversations so the sidebar cache is fully
        // populated. This means switching between conversations after login
        // never shows an empty view — messages are already in memory.
        const loadedMap = new Map<number | "new", Message[]>([
          ["new", [WELCOME_MESSAGE]],
        ]);
 
        await Promise.all(
          convs.map(async (conv) => {
            try {
              const storedMsgs = await getConversationMessages(conv.id);
              const loaded: Message[] = storedMsgs.map((m) => {
                if (m.role === "assistant") {
                  try {
                    const result = JSON.parse(m.content);
                    if (
                      result &&
                      typeof result === "object" &&
                      "sql" in result
                    ) {
                      return {
                        id: m.id.toString(),
                        content: "Here are your results:",
                        role: m.role as "user" | "assistant",
                        result,
                        timestamp: m.timestamp,
                        kind: "result" as const,
                      };
                    }
                  } catch {
                    /* plain text */
                  }
                }
                return {
                  id: m.id.toString(),
                  content: m.content,
                  role: m.role as "user" | "assistant",
                  timestamp: m.timestamp,
                };
              });
              loadedMap.set(
                conv.id,
                loaded.length > 0 ? loaded : [WELCOME_MESSAGE],
              );
            } catch (err) {
              console.error(`Failed to load messages for conv ${conv.id}`, err);
            }
          }),
        );
 
        // Write all conversations into the cache in one setState call
        setConvMessages(loadedMap);
 
        // Auto-activate the most recent conversation
        const latest = convs[0]; // ORDER BY created_at DESC from backend
        setActiveConvId(latest.id);
        activeConvIdRef.current = latest.id;
      })
      .catch(console.error)
      .finally(() => setSidebarLoading(false));
  }, [user]); // eslint-disable-line react-hooks/exhaustive-deps
 
  const handleLogout = async () => {
    await logout();
    router.replace("/login");
  };
 
  // ── Reset: clears backend session memory and active filters for the current
  //    conversation, but preserves the conversation record and all messages.
  const handleReset = async () => {
    const convId = activeConvIdRef.current;
 
    if (convId !== null) {
      try {
        // Clear the NL2SQL session memory on the backend (context window reset)
        await resetSession(convId);
        // Also clear any active filters from the session
        await clearSessionFilters(convId);
 
        // Show success toast
        setShowResetToast(true);
        setTimeout(() => setShowResetToast(false), 3000);
      } catch (err) {
        console.error("Failed to reset session", err);
      }
 
      // Clear active filters locally for this conversation
      setConvActiveFilters((prev) => {
        const next = new Map(prev);
        next.set(convId, {});
        return next;
      });
    }
  };
 
  // ── Stop: abort the current in-flight query ─────────────────────────────
  const handleStop = () => {
    stoppedByUserRef.current = true;
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
  };
 
  // ── New chat: sets up a blank view; DB conversation created on first send ─
  const handleNewChat = () => {
    setActiveConvId(null);
    activeConvIdRef.current = null;
    // Ensure the "new" slot has a welcome message, but don't wipe other convs
    setMessagesForConv("new", [WELCOME_MESSAGE]);
  };
 
  // ── Select a past conversation from the sidebar ───────────────────────────
  const handleSelectConversation = async (conv: Conversation) => {
    // Already viewing this conversation — do nothing
    if (conv.id === activeConvIdRef.current) return;
 
    // Switch active conversation immediately so the UI responds
    setActiveConvId(conv.id);
    activeConvIdRef.current = conv.id;
 
    // If we already have this conversation's messages in the in-memory cache
    // (e.g. the user sent a message here this session), use them directly.
    // This prevents a DB fetch from returning stale/incomplete data when
    // appendMessage fire-and-forget calls haven't finished yet.
    const cached = convMessages.get(conv.id);
    if (cached && cached.length > 0) return;
 
    // Not in cache — fetch from DB (e.g. restoring a past conversation)
    try {
      const storedMsgs = await getConversationMessages(conv.id);
      const loaded: Message[] = storedMsgs.map((m) => {
        if (m.role === "assistant") {
          try {
            const result = JSON.parse(m.content);
            if (result && typeof result === "object" && "sql" in result) {
              return {
                id: m.id.toString(),
                content: "Here are your results:",
                role: m.role,
                result,
                timestamp: m.timestamp,
                kind: "result" as const,
              };
            }
          } catch {
            // plain text — fall through
          }
        }
        return {
          id: m.id.toString(),
          content: m.content,
          role: m.role as "user" | "assistant",
          timestamp: m.timestamp,
        };
      });
      setMessagesForConv(
        conv.id,
        loaded.length > 0 ? loaded : [WELCOME_MESSAGE],
      );
    } catch (err) {
      console.error("Failed to load conversation messages", err);
    }
  };
 
  // ── Delete a conversation from the sidebar ────────────────────────────────
  const handleDeleteConversation = async (
    e: React.MouseEvent,
    conv: Conversation,
  ) => {
    e.stopPropagation(); // prevent triggering handleSelectConversation
    if (!confirm(`Delete "${conv.title}"? This cannot be undone.`)) return;
 
    setDeletingId(conv.id);
    try {
      await deleteConversation(conv.id);
      // Remove from sidebar list
      setConversations((prev) => prev.filter((c) => c.id !== conv.id));
      // If the deleted conversation was active, start a fresh view
      if (activeConvIdRef.current === conv.id) {
        setActiveConvId(null);
        activeConvIdRef.current = null;
      }
      // Remove from message cache
      setConvMessages((prev) => {
        const next = new Map(prev);
        next.delete(conv.id);
        if (!next.has("new")) next.set("new", [WELCOME_MESSAGE]);
        return next;
      });
    } catch (err) {
      console.error("Failed to delete conversation", err);
    } finally {
      setDeletingId(null);
    }
  };
 
  // ── Send a message ────────────────────────────────────────────────────────
  const handleSend = async (content: string) => {
    const userMessage: Message = {
      id: `${Date.now()}`,
      role: "user",
      content,
      timestamp: new Date().toISOString(),
      kind: "query",
    };
 
    // Use "new" key until we have a real convId from the DB
    setMessagesForConv(activeConvIdRef.current ?? "new", (prev) => [
      ...prev,
      userMessage,
    ]);
 
    // Create a conversation in the DB on the first message of a new chat.
    // Do this BEFORE marking loading so the key is correct.
    let convId = activeConvIdRef.current;
    if (convId === null) {
      try {
        const created = await createConversation();
        convId = created.id;
        activeConvIdRef.current = convId;
        setActiveConvId(convId);
        // Migrate messages from the "new" slot to the real conversation ID
        setConvMessages((prev) => {
          const next = new Map(prev);
          const newMsgs = next.get("new") ?? [WELCOME_MESSAGE];
          next.set(convId!, newMsgs);
          next.set("new", [WELCOME_MESSAGE]); // reset the "new" slot
          return next;
        });
        getConversations().then(setConversations).catch(console.error);
      } catch (err) {
        console.error("Failed to create conversation", err);
        return;
      }
    }
 
    // Mark THIS conversation as loading — not a global flag
    setConvLoading(convId, true);
 
    // Snapshot the convId this query belongs to.
    // After the async LLM call resolves, we check whether the user has
    // switched to a different conversation. If they have, we skip the
    // setMessages call so we don't overwrite the wrong conversation's view.
    const queryConvId = convId;
 
    // Persist user message to DB
    appendMessage(convId, "user", content).catch(console.error);
 
    // Build history for Agent 0 context (exclude welcome message)
    const conversationHistory = messages
      .filter((m) => m.id !== "welcome")
      .map((m) => ({ role: m.role, content: m.content, kind: m.kind }));
 
    // Create a fresh AbortController for this query
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    stoppedByUserRef.current = false;
 
    try {
      const result = await queryBackend(
        content,
        sessionId,
        convId,
        chatMode,
        conversationHistory,
        abortController.signal,
      );
 
      const needsClarification = Boolean(
        result.query_plan?.needs_clarification,
      );
      const clarificationQuestion = result.query_plan?.clarification_question;
 
      const assistantMessage: Message = {
        id: `${Date.now() + 1}`,
        role: "assistant",
        content: needsClarification
          ? clarificationQuestion || "Could you clarify your request?"
          : !result.executed && (result.warnings?.length ?? 0) > 0
            ? result.warnings[0]
            : "Here are your results:",
        result,
        timestamp: new Date().toISOString(),
        kind: needsClarification
          ? "clarification"
          : !result.executed && (result.warnings?.length ?? 0) > 0
            ? "error"
            : "result",
      };
 
      // Always update the correct conversation's messages regardless of
      // which conversation is currently viewed. setMessagesForConv uses
      // the queryConvId key, so it never touches other conversations.
      setMessagesForConv(queryConvId, (prev) => [...prev, assistantMessage]);
 
      // Update active filters for this conversation
      if (result.active_filters !== undefined) {
        setConvActiveFilters((prev) => {
          const next = new Map(prev);
          next.set(queryConvId, result.active_filters ?? {});
          return next;
        });
      }
 
      // Always persist to DB regardless of which view is active
      appendMessage(queryConvId, "assistant", JSON.stringify(result)).catch(
        console.error,
      );
 
      // Refresh sidebar title
      getConversations().then(setConversations).catch(console.error);
    } catch (error) {
      const wasStopped = stoppedByUserRef.current;
      const errorMessage: Message = {
        id: `${Date.now() + 1}`,
        role: "assistant",
        content: "Sorry, something went wrong.",
        result: {
          data: [],
          sql: "",
          query_plan: {
            intent: "unsupported",
            metric: "",
            dimensions: [],
            filters: [],
            limit: 0,
            needs_clarification: false,
            clarification_question: null,
          },
          guardrails: { ok: false, warnings: [] },
          error:
            error instanceof Error && error.name === "AbortError"
              ? wasStopped
                ? "Query stopped by user."
                : "Request timed out — the query was too complex or the model took too long."
              : "Failed to connect to server. Make sure the backend is running.",
        },
        timestamp: new Date().toISOString(),
        kind: "error",
      };
      // Always update the correct conversation's messages
      setMessagesForConv(queryConvId, (prev) => [...prev, errorMessage]);
    } finally {
      abortControllerRef.current = null;
      stoppedByUserRef.current = false;
      setConvLoading(queryConvId, false);
    }
  };
 
  if (loading || !user) return null;
 
  return (
    <div className="flex h-screen overflow-hidden bg-white">
      {/* ── Reset success toast ──────────────────────────────── */}
      <div
        className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2.5 px-4 py-3 rounded-xl shadow-lg border border-green-200 bg-white text-green-700 text-sm font-medium transition-all duration-300 ${
          showResetToast
            ? "opacity-100 translate-y-0 pointer-events-auto"
            : "opacity-0 translate-y-2 pointer-events-none"
        }`}
      >
        <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0" />
        Session reset successful — memory and filters cleared.
      </div>
 
      {/* ── Sidebar ─────────────────────────────────────────── */}
      <aside
        className={`flex flex-col border-r border-gray-100 bg-gray-50 transition-all duration-200 ${
          sidebarOpen ? "w-64 min-w-[16rem]" : "w-0 min-w-0 overflow-hidden"
        }`}
      >
        {/* Sidebar header */}
        <div className="flex items-center justify-between px-3 py-3 border-b border-gray-100">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
            History
          </span>
          <button
            onClick={handleNewChat}
            title="New chat"
            className="flex items-center space-x-1 text-xs text-gray-400 hover:text-blue-500 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New</span>
          </button>
        </div>
 
        {/* Conversation list */}
        <div className="flex-1 overflow-y-auto py-2">
          {sidebarLoading ? (
            <p className="px-3 py-2 text-xs text-gray-400">Loading…</p>
          ) : conversations.length === 0 ? (
            <p className="px-3 py-2 text-xs text-gray-400">
              No past conversations.
            </p>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                className={`group flex items-center mx-1 my-0.5 rounded-md transition-colors ${
                  activeConvId === conv.id
                    ? "bg-blue-50 text-blue-700"
                    : "text-gray-700 hover:bg-gray-100"
                }`}
                style={{ width: "calc(100% - 8px)" }}
              >
                {/* Clickable area — load conversation */}
                <button
                  onClick={() => handleSelectConversation(conv)}
                  className="flex-1 text-left px-3 py-2 min-w-0"
                >
                  <div className="flex items-start space-x-2">
                    <MessageSquare className="w-3 h-3 mt-0.5 flex-shrink-0 text-gray-400 group-hover:text-gray-500" />
                    <div className="min-w-0">
                      <p className="text-xs font-medium truncate leading-snug">
                        {conv.title}
                      </p>
                      <p className="text-[10px] text-gray-400 mt-0.5">
                        {new Date(conv.created_at).toLocaleDateString(
                          undefined,
                          {
                            month: "short",
                            day: "numeric",
                            year: "numeric",
                          },
                        )}
                      </p>
                    </div>
                  </div>
                </button>
 
                {/* Delete button — only visible on hover */}
                <button
                  onClick={(e) => handleDeleteConversation(e, conv)}
                  disabled={deletingId === conv.id}
                  title="Delete conversation"
                  className="opacity-0 group-hover:opacity-100 flex-shrink-0 p-1.5 mr-1 rounded text-gray-400 hover:text-red-500 hover:bg-red-50 transition-all disabled:opacity-40"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            ))
          )}
        </div>
      </aside>
 
      {/* ── Main area ───────────────────────────────────────── */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 bg-white/80 backdrop-blur-sm sticky top-0 z-10">
          <div className="flex items-center space-x-2">
            <button
              onClick={() => setSidebarOpen((v) => !v)}
              title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
              className="text-gray-400 hover:text-gray-600 transition-colors"
            >
              {sidebarOpen ? (
                <ChevronLeft className="w-4 h-4" />
              ) : (
                <ChevronRight className="w-4 h-4" />
              )}
            </button>
            <span className="text-sm font-semibold text-gray-700">
              ANCHOR Cancer Analytics
            </span>
            {isAdmin && (
              <span className="text-[10px] uppercase tracking-widest font-bold text-blue-500 bg-blue-50 px-2 py-0.5 rounded-full">
                Admin
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {/* Fast / Strict mode */}
            <button
              onClick={() =>
                setChatMode((prev) => (prev === "fast" ? "strict" : "fast"))
              }
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                chatMode === "fast"
                  ? "bg-emerald-100 text-emerald-700 border-emerald-200"
                  : "bg-indigo-100 text-indigo-700 border-indigo-200"
              }`}
              title="fast: fewer clarifications, strict: ask for precision"
            >
              {chatMode === "fast" ? "Fast Mode" : "Strict Mode"}
            </button>
 
            {/* Debug toggle — available to all users */}
            <button
              onClick={() => setDebugMode((prev) => !prev)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                debugMode
                  ? "bg-amber-100 text-amber-700 border border-amber-200"
                  : "bg-gray-100 text-gray-500 border border-gray-200 hover:bg-gray-200"
              }`}
            >
              <Bug className="w-3.5 h-3.5" />
              {debugMode ? "Debug ON" : "Debug OFF"}
            </button>
 
            {/* Reset session */}
            <button
              onClick={handleReset}
              disabled={isLoading || activeConvId === null}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-gray-200 bg-gray-100 text-gray-500 hover:bg-red-50 hover:text-red-600 hover:border-red-200 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              title="Reset session memory and filters for this conversation (keeps chat history)"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Reset
            </button>
 
            {/* Profile pill with dropdown */}
            <div className="relative group">
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-gray-50 border border-gray-200 cursor-pointer group-hover:border-gray-300 transition-colors">
                <div
                  className={
                    "w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold text-white " +
                    (isAdmin ? "bg-purple-500" : "bg-blue-500")
                  }
                >
                  {user.username.charAt(0).toUpperCase()}
                </div>
                <div className="flex flex-col leading-none">
                  <span className="text-xs font-semibold text-gray-700">
                    {user.username}
                  </span>
                  <span
                    className={
                      "text-[9px] font-medium uppercase tracking-widest " +
                      (isAdmin ? "text-purple-500" : "text-blue-400")
                    }
                  >
                    {user.role}
                  </span>
                </div>
              </div>
              <div className="absolute right-0 top-full mt-1 w-44 bg-white border border-gray-100 rounded-xl shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-150 z-50 py-1">
                {isAdmin && (
                  <button
                    onClick={() => router.push("/admin")}
                    className="flex items-center gap-2 w-full px-3 py-2 text-xs text-indigo-600 hover:bg-indigo-50 transition-colors"
                  >
                    <ShieldAlert className="w-3.5 h-3.5" />
                    Admin Dashboard
                  </button>
                )}
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-2 w-full px-3 py-2 text-xs text-gray-500 hover:bg-red-50 hover:text-red-600 transition-colors"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  Sign out
                </button>
              </div>
            </div>
          </div>
        </div>
 
        {/* Active filters pill bar */}
        <div className="px-4 py-2 border-b border-gray-100 bg-gray-50/50 flex items-center gap-2 flex-wrap min-h-[36px]">
          <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest shrink-0">
            Filters
          </span>
          {Object.keys(activeFilters).length === 0 ? (
            <span className="text-[10px] text-gray-300 italic">
              No filters applied
            </span>
          ) : (
            Object.entries(activeFilters).map(([field, value]) => {
              const label = field
                .replace(/_/g, " ")
                .replace(/\w/g, (c) => c.toUpperCase());
              const display = Array.isArray(value)
                ? (value as unknown[]).join(", ")
                : String(value);
              return (
                <span
                  key={field}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-100 text-blue-700 border border-blue-200"
                >
                  <span className="text-blue-400">{label}:</span>
                  <span className="truncate max-w-[120px]" title={display}>
                    {display}
                  </span>
 
                </span>
              );
            })
          )}
        </div>
 
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              isUser={message.role === "user"}
              debugMode={debugMode}
            />
          ))}
 
          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-gray-100 rounded-lg p-4">
                <div className="flex space-x-2">
                  <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" />
                  <div
                    className="w-2 h-2 bg-gray-500 rounded-full animate-bounce"
                    style={{ animationDelay: "0.2s" }}
                  />
                  <div
                    className="w-2 h-2 bg-gray-500 rounded-full animate-bounce"
                    style={{ animationDelay: "0.4s" }}
                  />
                </div>
              </div>
            </div>
          )}
        </div>
 
        <ChatInput
          onSend={handleSend}
          onStop={handleStop}
          isLoading={isLoading}
          disabled={false}
        />
      </div>
    </div>
  );
}