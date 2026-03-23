"use client";

import { useEffect, useState } from "react";
import { Message } from "../../lib/types";
import { queryBackend } from "../../lib/api";
import { MessageBubble } from "../../components/MessageBubble";
import { ChatInput } from "../../components/ChatInput";
import { Bug } from "lucide-react";

const STORAGE_KEY = "nccs_chat_history_v1";

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [debugMode, setDebugMode] = useState(false);
  const [chatMode, setChatMode] = useState<"fast" | "strict">("fast");

  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as Message[];
        if (Array.isArray(parsed) && parsed.length > 0) {
          const normalized = parsed.map((m, idx) => ({
            ...m,
            role: m.role ?? (idx % 2 === 0 ? "assistant" : "user"),
            timestamp: m.timestamp ?? new Date().toISOString(),
          })) as Message[];
          setMessages(normalized);
          return;
        }
      } catch {
        // fall through to default welcome message
      }
    }

    setMessages([
      {
        id: "1",
        role: "assistant",
        content: "Hello! Ask me anything about the cancer data.",
        timestamp: new Date().toISOString(),
        kind: "result",
      },
    ]);
  }, []);

  useEffect(() => {
    if (messages.length > 0) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    }
  }, [messages]);

  const handleSend = async (content: string) => {
    const userMessage: Message = {
      id: `${Date.now()}`,
      role: "user",
      content,
      timestamp: new Date().toISOString(),
      kind: "query",
    };

    const historyForBackend = [...messages, userMessage];
    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const result = await queryBackend(content, historyForBackend, chatMode);

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
    } catch {
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
          error: "Failed to connect to server",
        },
        timestamp: new Date().toISOString(),
        kind: "error",
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-screen max-w-6xl mx-auto">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 bg-white/80 backdrop-blur-sm sticky top-0 z-10">
        <h1 className="text-sm font-semibold text-gray-700">ANCHOR Cancer Analytics</h1>
        <div className="flex items-center gap-2">
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
        </div>
      </div>

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

      <ChatInput onSend={handleSend} disabled={isLoading} />
    </div>
  );
}
