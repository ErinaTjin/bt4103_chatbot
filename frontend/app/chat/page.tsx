"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Conversation, Message } from "@/lib/types";
import { queryBackend, getConversations, createConversation, getConversationMessages, appendMessage } from "@/lib/api";
import { MessageBubble } from "@/components/MessageBubble";
import { ChatInput } from "@/components/ChatInput";
import { useAuth } from "@/context/AuthContext";
import { ChevronLeft, ChevronRight, LogOut, MessageSquare, Plus } from "lucide-react";

export default function ChatPage() {
  const router = useRouter();
  const { user, isAdmin, loading, logout } = useAuth();

  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      content: "Hello! Ask me anything about the cancer data.",
      role: "assistant",
      timestamp: new Date().toISOString(),
    },
  ]);
  const [isLoading, setIsLoading] = useState(false);

  // Sidebar state
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [sidebarLoading, setSidebarLoading] = useState(false);

  // Track whether the current session already has a DB conversation created
  const activeConvIdRef = useRef<number | null>(null);

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

  const handleLogout = () => {
    logout();
    router.replace("/login");
  };

  // Start a fresh chat without loading any past conversation
  const handleNewChat = () => {
    setActiveConvId(null);
    activeConvIdRef.current = null;
    setMessages([
      {
        id: "1",
        content: "Hello! Ask me anything about the cancer data.",
        role: "assistant",
        timestamp: new Date().toISOString(),
      },
    ]);
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
          : [
              {
                id: "1",
                content: "Hello! Ask me anything about the cancer data.",
                role: "assistant",
                timestamp: new Date().toISOString(),
              },
            ]
      );
      setActiveConvId(conv.id);
      activeConvIdRef.current = conv.id;
    } catch (err) {
      console.error("Failed to load conversation messages", err);
    }
  };

  const handleSend = async (content: string) => {
    const userMessage: Message = {
      id: Date.now().toString(),
      content,
      role: "user",
      timestamp: new Date().toISOString(),
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

    try {
      const conversationHistory = messages
        .filter((m) => m.role)
        .map((m) => ({
          role: m.role!,
          content:
            m.role === "assistant" && m.result?.query_plan?.intent_summary
              ? m.result.query_plan.intent_summary
              : m.content,
          kind: m.kind,
        }));

      const result = await queryBackend(content, conversationHistory);

      const assistantContent = "Here are your results:";
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: assistantContent,
        role: "assistant",
        result,
        timestamp: new Date().toISOString(),
        kind: "result",
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
        id: (Date.now() + 1).toString(),
        content: "Sorry, something went wrong.",
        role: "assistant",
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
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
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
            <span className="text-sm font-semibold text-gray-700">ANCHOR</span>
            {isAdmin && (
              <span className="text-[10px] uppercase tracking-widest font-bold text-blue-500 bg-blue-50 px-2 py-0.5 rounded-full">
                Admin
              </span>
            )}
          </div>
          <div className="flex items-center space-x-3">
            <span className="text-xs text-gray-400">{user.username}</span>
            <button
              onClick={handleLogout}
              className="flex items-center space-x-1 text-xs text-gray-400 hover:text-red-500 transition-colors"
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
              debugMode={isAdmin}
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
