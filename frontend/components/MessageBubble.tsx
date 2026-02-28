"use client";

import { Message } from "@/lib/types";
import { ResultsTable } from "./ResultsTable";

interface MessageBubbleProps {
  message: Message;
  isUser?: boolean;
}

export function MessageBubble({ message, isUser = false }: MessageBubbleProps) {
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-3xl ${isUser ? "bg-blue-600 text-white" : "bg-gray-100"} rounded-lg p-4`}
      >
        <p className="text-sm">{message.content}</p>

        {message.result && !message.result.error && (
          <div className="mt-4">
            <ResultsTable data={message.result.data} />

            {message.result.sql && (
              <details className="mt-2 text-xs">
                <summary className="cursor-pointer text-white hover:text-orange-500 transition-colors duration-200">
                  View SQL
                </summary>
                <pre className="mt-2 p-2 bg-gray-800 text-green-400 rounded overflow-x-auto">
                  {message.result.sql}
                </pre>
              </details>
            )}

            {message.result.warnings && message.result.warnings.length > 0 && (
              <div className="mt-2 text-sm text-yellow-700 bg-yellow-50 p-2 rounded">
                {message.result.warnings.map((w, i) => (
                  <p key={i}> Warning: {w}</p>
                ))}
              </div>
            )}
          </div>
        )}

        {message.result?.error && (
          <p className="mt-2 text-sm text-red-600 bg-red-50 p-2 rounded">
            Error: {message.result.error}
          </p>
        )}
      </div>
    </div>
  );
}
