"use client";

import { useState } from "react";
import { Send, Square } from "lucide-react";
 
interface ChatInputProps {
  onSend: (message: string) => void;
  onStop?: () => void;   // called when user clicks the stop button
  disabled?: boolean;
  isLoading?: boolean;   // true while a query is in flight
}
 
export function ChatInput({ onSend, onStop, disabled, isLoading }: ChatInputProps) {
  const [input, setInput] = useState("");
 
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !disabled && !isLoading) {
      onSend(input.trim());
      setInput("");
    }
  };
 
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as React.FormEvent);
    }
  };
 
  return (
    <form onSubmit={handleSubmit} className="flex gap-2 p-4 border-t">
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={isLoading ? "Query is running..." : "Ask a question..."}
        disabled={disabled || isLoading}
        className="flex-1 px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 text-gray-900"
      />
 
      {isLoading ? (
        // Stop button — shown while query is running
        <button
          type="button"
          onClick={onStop}
          className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors flex items-center gap-1.5"
          title="Stop query"
        >
          <Square className="w-4 h-4 fill-white" />
        </button>
      ) : (
        // Send button — shown when idle
        <button
          type="submit"
          disabled={disabled || !input.trim()}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
        >
          <Send className="w-5 h-5" />
        </button>
      )}
    </form>
  );
}