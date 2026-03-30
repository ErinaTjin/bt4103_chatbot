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
  Filter,
  ShieldAlert,
} from "lucide-react";
 
const SESSION_KEY = "anchor_session_id";
const MESSAGES_KEY = "anchor_chat_messages";
 
const WELCOME_MESSAGE: Message = {
  id: "1",
  role: "assistant",
  content: "Hello! Ask me anything about the cancer data.",
  timestamp: new Date().toISOString(),
  kind: "result",
};
 
export default function ChatPage() {
  const router = useRouter();
  const { user, isAdmin, loading, logout } = useAuth();
 
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);
  const [debugMode, setDebugMode] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return sessionStorage.getItem("anchor_debug_mode") === "true";
  });
  const [chatMode, setChatMode] = useState<"fast" | "strict">("fast");
 
  // Sidebar state
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [sidebarLoading, setSidebarLoading] = useState(false);
 
  // Track whether the current session already has a DB conversation created
  const activeConvIdRef = useRef<number | null>(null);
 
  // Generate or restore session ID on mount
  useEffect(() => {
    let id = sessionStorage.getItem(SESSION_KEY);
    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem(SESSION_KEY, id);
    }
    setSessionId(id);
    const saved = sessionStorage.getItem(MESSAGES_KEY);
    if (saved) {
      try { setMessages(JSON.parse(saved)); }
      catch { setMessages([WELCOME_MESSAGE]); }
    } else {
      setMessages([WELCOME_MESSAGE]);
    }
  }, []);
 
  // Save messages to sessionStorage whenever they change
  useEffect(() => {
    if (messages.length > 0) {
      sessionStorage.setItem(MESSAGES_KEY, JSON.stringify(messages));
    }
  }, [messages]);

  // Persist debug mode preference across page refreshes
  useEffect(() => {
    sessionStorage.setItem("anchor_debug_mode", String(debugMode));
  }, [debugMode]);
 
  // Redirect to login if not authenticated
  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login");
    }
  }, [loading, user, router]);
 
  // Load conversations list once user is authenticated
  useEffect(() => {
    if (!user) return;
    setSidebarLoading(true);
    getConversations()
      .then(setConversations)
      .catch(console.error)
      .finally(() => setSidebarLoading(false));
  }, [user]);
 
  const handleLogout = async () => {
    await logout();
    router.replace("/login");
  };
 
  // Reset session: clear server-side state, generate new session ID, clear messages
  const handleReset = async () => {
    await resetSession();  // user-keyed, no session_id needed
    const newId = crypto.randomUUID();
    sessionStorage.setItem(SESSION_KEY, newId);
    sessionStorage.removeItem(MESSAGES_KEY);
    setSessionId(newId);
    setMessages([WELCOME_MESSAGE]);
    setActiveConvId(null);
    activeConvIdRef.current = null;
  };
 
  const handleClearFilters = async () => {
    await clearSessionFilters();  // user-keyed, no session_id needed
  };
 
  // Start a fresh chat without loading any past conversation
  const handleNewChat = () => {
    setActiveConvId(null);
    activeConvIdRef.current = null;
    setMessages([WELCOME_MESSAGE]);
  };
 
  // Load a past conversation into the chat view
  const handleSelectConversation = async (conv: Conversation) => {
    try {
      const storedMsgs = await getConversationMessages(conv.id);
      const loaded: Message[] = storedMsgs.map((m) => {
        // Assistant messages are stored as JSON-serialised QueryResponse
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
            // not JSON — fall through to plain text
          }
        }
        return {
          id: m.id.toString(),
          content: m.content,
          role: m.role,
          timestamp: m.timestamp,
        };
      });
      setMessages(
        loaded.length > 0
          ? loaded
          : [WELCOME_MESSAGE]
      );
      setActiveConvId(conv.id);
      activeConvIdRef.current = conv.id;
    } catch (err) {
      console.error("Failed to load conversation messages", err);
    }
  };
 
  const handleSend = async (content: string) => {
    const userMessage: Message = {
      id: `${Date.now()}`,
      role: "user",
      content,
      timestamp: new Date().toISOString(),
      kind: "query",
    };
 
    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);
 
    // Ensure a conversation exists in the DB for this session
    let convId = activeConvIdRef.current;
    if (convId === null) {
      try {
        const created = await createConversation();
        convId = created.id;
        activeConvIdRef.current = convId;
        setActiveConvId(convId);
        // Refresh sidebar list
        getConversations().then(setConversations).catch(console.error);
      } catch (err) {
        console.error("Failed to create conversation", err);
      }
    }
 
    // Persist the user message
    if (convId !== null) {
      appendMessage(convId, "user", content).catch(console.error);
    }
 
    // Build conversation history from existing messages
    const conversationHistory = messages
      .filter(m => m.id !== "1")  // exclude welcome message
      .map(m => ({
        role: m.role,
        content: m.content,
        kind: m.kind,
      }));
 
    try {
      const result = await queryBackend(content, sessionId, chatMode, conversationHistory);
 
      const needsClarification = Boolean(result.query_plan?.needs_clarification);
      const clarificationQuestion = result.query_plan?.clarification_question;
 
      const assistantMessage: Message = {
        id: `${Date.now() + 1}`,
        role: "assistant",
        content: needsClarification
          ? clarificationQuestion || "Could you clarify your request?"
          : "Here are your results:",
        result,
        timestamp: new Date().toISOString(),
        kind: needsClarification ? "clarification" : "result",
      };
 
      setMessages((prev) => [...prev, assistantMessage]);
 
      // Persist assistant message — store full result as JSON so it can be restored on reload
      if (convId !== null) {
        appendMessage(convId, "assistant", JSON.stringify(result)).catch(console.error);
      }
 
      // Refresh sidebar so updated title shows
      getConversations().then(setConversations).catch(console.error);
    } catch (error) {
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
          error: error instanceof Error && error.name === "AbortError"
            ? "Request timed out — the query was too complex or the model took too long. Try rephrasing or breaking it into a simpler question."
            : "Failed to connect to server. Make sure the backend is running.",
        },
        timestamp: new Date().toISOString(),
        kind: "error",
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };
 
  if (loading || !user) return null;
 
  return (
    <div className="flex h-screen overflow-hidden bg-white">
      {/* ── Sidebar ─────────────────────────────────────────── */}
      <aside
        className={`flex flex-col border-r border-gray-100 bg-gray-50 transition-all duration-200 ${
          sidebarOpen ? "w-64 min-w-[16rem]" : "w-0 min-w-0 overflow-hidden"
        }`}
      >
        {/* Sidebar header */}
        <div className="flex items-center justify-between px-3 py-3 border-b border-gray-100">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">History</span>
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
            <p className="px-3 py-2 text-xs text-gray-400">No past conversations.</p>
          ) : (
            conversations.map((conv) => (
              <button
                key={conv.id}
                onClick={() => handleSelectConversation(conv)}
                className={`w-full text-left px-3 py-2 rounded-md mx-1 my-0.5 transition-colors group ${
                  activeConvId === conv.id
                    ? "bg-blue-50 text-blue-700"
                    : "text-gray-700 hover:bg-gray-100"
                }`}
                style={{ width: "calc(100% - 8px)" }}
              >
                <div className="flex items-start space-x-2">
                  <MessageSquare className="w-3 h-3 mt-0.5 flex-shrink-0 text-gray-400 group-hover:text-gray-500" />
                  <div className="min-w-0">
                    <p className="text-xs font-medium truncate leading-snug">{conv.title}</p>
                    <p className="text-[10px] text-gray-400 mt-0.5">
                      {new Date(conv.created_at).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}
                    </p>
                  </div>
                </div>
              </button>
            ))
          )}
        </div>
      </aside>
 
      {/* ── Main area ───────────────────────────────────────── */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 bg-white/80 backdrop-blur-sm sticky top-0 z-10">
          <div className="flex items-center space-x-2">
            {/* Toggle sidebar button */}
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
            <span className="text-sm font-semibold text-gray-700">ANCHOR Cancer Analytics</span>
            {isAdmin && (
              <span className="text-[10px] uppercase tracking-widest font-bold text-blue-500 bg-blue-50 px-2 py-0.5 rounded-full">
                Admin
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {/* Fast / Strict mode toggle */}
            <button
              onClick={() => setChatMode((prev) => (prev === "fast" ? "strict" : "fast"))}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                chatMode === "fast"
                  ? "bg-emerald-100 text-emerald-700 border-emerald-200"
                  : "bg-indigo-100 text-indigo-700 border-indigo-200"
              }`}
              title="fast: fewer clarifications, strict: ask for precision"
            >
              {chatMode === "fast" ? "Fast Mode" : "Strict Mode"}
            </button>
 
            {/* Debug toggle — admin only */}
            {isAdmin && (
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
            )}
 
            {/* Admin dashboard link — admin only */}
            {isAdmin && (
              <button
                onClick={() => router.push("/admin")}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-indigo-200 bg-indigo-50 text-indigo-600 hover:bg-indigo-100 transition-colors"
                title="Admin dashboard"
              >
                <ShieldAlert className="w-3.5 h-3.5" />
                Dashboard
              </button>
            )}

            {/* Clear filters button */}
            <button
              onClick={handleClearFilters}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-gray-200 bg-gray-100 text-gray-500 hover:bg-orange-50 hover:text-orange-600 hover:border-orange-200 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              title="Clear active filters (e.g. cancer type, year) but keep chat history"
            >
              <Filter className="w-3.5 h-3.5" />
              Clear filters
            </button>
 
            {/* Reset session button */}
            <button
              onClick={handleReset}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-gray-200 bg-gray-100 text-gray-500 hover:bg-red-50 hover:text-red-600 hover:border-red-200 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              title="Clear conversation and start a new session"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Reset
            </button>
 
            {/* Profile pill */}
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-gray-50 border border-gray-200">
              <div className={"w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold text-white " + (isAdmin ? "bg-purple-500" : "bg-blue-500")}>
                {user.username.charAt(0).toUpperCase()}
              </div>
              <div className="flex flex-col leading-none">
                <span className="text-xs font-semibold text-gray-700">{user.username}</span>
                <span className={"text-[9px] font-medium uppercase tracking-widest " + (isAdmin ? "text-purple-500" : "text-blue-400")}>
                  {user.role}
                </span>
              </div>
            </div>
            <button
              onClick={handleLogout}
              className="flex items-center space-x-1 text-xs text-gray-400 hover:text-red-500 transition-colors"
              title="Sign out"
            >
              <LogOut className="w-3.5 h-3.5" />
              <span>Sign out</span>
            </button>
          </div>
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
                  <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: "0.2s" }} />
                  <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: "0.4s" }} />
                </div>
              </div>
            </div>
          )}
        </div>
 
        <ChatInput onSend={handleSend} disabled={isLoading} />
      </div>
    </div>
  );
}
