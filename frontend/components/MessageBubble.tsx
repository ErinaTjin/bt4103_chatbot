"use client";
import { Message } from "@/lib/types";
import { ResultsTable } from "./ResultsTable";
import { ResultsChart } from "./ResultsChart";
import { SummaryCard } from "./SummaryCard";
import { generateSummary } from "@/lib/summaryGenerator";
import {
  Database,
  FileJson,
  AlertCircle,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { useState } from "react";

interface MessageBubbleProps {
  message: Message;
  isUser?: boolean;
}

export function MessageBubble({ message, isUser = false }: MessageBubbleProps) {
  const [showSql, setShowSql] = useState(false);
  const [showAgentWork, setShowAgentWork] = useState(false);
  const visualization =
    message.result?.query_plan?.output?.preferred_visualization;
  const showChart =
    visualization &&
    visualization !== "table" &&
    (message.result?.data?.length ?? 0) > 0;

  // Generate summary from SQL results
  const summary = message.result?.data && message.result?.query_plan?.intent
    ? generateSummary(message.result.data, message.result.query_plan.intent)
    : null;

  return (
    <div
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"} animate-in fade-in slide-in-from-bottom-2 duration-300`}
    >
      <div
        className={`max-w-[85%] ${
          isUser
            ? "bg-blue-600 text-white shadow-lg shadow-blue-200/50"
            : "bg-white border border-gray-100 shadow-sm"
        } rounded-2xl p-5`}
      >
        <p
          className={`text-sm leading-relaxed ${isUser ? "text-white" : "text-gray-800 font-medium"}`}
        >
          {message.content}
        </p>

        {message.result && !message.result.error && (
          <div className="mt-6 space-y-4">
            {showChart ? (
              <div className="space-y-4">
                <ResultsChart data={message.result.data} type={visualization} />
                <div className="bg-gray-50/50 rounded-xl p-3 border border-gray-100/50">
                  <p className="text-[10px] text-gray-400 uppercase tracking-widest font-bold mb-3 flex items-center">
                    <Database className="w-3 h-3 mr-1" /> Data Source
                  </p>
                  <ResultsTable data={message.result.data} />
                </div>
              </div>
            ) : (
              <ResultsTable data={message.result.data} />
            )}

            {summary && <SummaryCard summary={summary} />}

            <div className="pt-2 border-t border-gray-100 space-y-3">
              {message.result.sql && (
                <div>
                  <button
                    onClick={() => setShowSql(!showSql)}
                    className={`flex items-center text-[10px] uppercase tracking-widest font-bold transition-colors ${
                      isUser
                        ? "text-blue-100 hover:text-white"
                        : "text-gray-400 hover:text-blue-600"
                    }`}
                  >
                    {showSql ? (
                      <ChevronUp className="w-3 h-3 mr-1" />
                    ) : (
                      <ChevronDown className="w-3 h-3 mr-1" />
                    )}
                    {showSql ? "Hide" : "View"} SQL
                  </button>
                  {showSql && (
                    <div className="mt-3 animate-in zoom-in-95 duration-200">
                      <div className="relative group">
                        <div className="absolute top-2 right-2 flex space-x-2">
                          <Database className="w-3 h-3 text-gray-500" />
                        </div>
                        <pre className="p-4 bg-gray-900 text-blue-300 rounded-xl text-[11px] font-mono leading-relaxed overflow-x-auto border border-gray-800">
                          {message.result.sql}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {(message.result.plan_agent1 ||
                message.result.plan_agent2 ||
                message.result.query_plan) && (
                <div>
                  <button
                    onClick={() => setShowAgentWork(!showAgentWork)}
                    className={`flex items-center text-[10px] uppercase tracking-widest font-bold transition-colors ${
                      isUser
                        ? "text-blue-100 hover:text-white"
                        : "text-gray-400 hover:text-blue-600"
                    }`}
                  >
                    {showAgentWork ? (
                      <ChevronUp className="w-3 h-3 mr-1" />
                    ) : (
                      <ChevronDown className="w-3 h-3 mr-1" />
                    )}
                    {showAgentWork ? "Hide" : "View"} Agent Work
                  </button>
                  {showAgentWork && (
                    <div className="mt-3 space-y-3 animate-in zoom-in-95 duration-200">
                      {message.result.plan_agent1 && (
                        <div className="p-3 bg-blue-50/50 rounded-xl border border-blue-100/50">
                          <p className="text-[10px] text-blue-500 uppercase tracking-widest font-bold mb-2 flex items-center">
                            <FileJson className="w-3 h-3 mr-1" /> Agent 1:
                            Business Plan
                          </p>
                          <pre className="text-[10px] text-gray-500 overflow-x-auto">
                            {JSON.stringify(
                              message.result.plan_agent1,
                              null,
                              2,
                            )}
                          </pre>
                        </div>
                      )}

                      {message.result.plan_agent2 && (
                        <div className="p-3 bg-purple-50/50 rounded-xl border border-purple-100/50">
                          <p className="text-[10px] text-purple-500 uppercase tracking-widest font-bold mb-2 flex items-center">
                            <FileJson className="w-3 h-3 mr-1" /> Agent 2:
                            Resolved Plan
                          </p>
                          <pre className="text-[10px] text-gray-500 overflow-x-auto">
                            {JSON.stringify(
                              message.result.plan_agent2,
                              null,
                              2,
                            )}
                          </pre>
                        </div>
                      )}

                      {message.result.query_plan && (
                        <div className="p-3 bg-gray-50 rounded-xl border border-gray-100">
                          <p className="text-[10px] text-gray-400 uppercase tracking-widest font-bold mb-2 flex items-center">
                            <FileJson className="w-3 h-3 mr-1" /> Final
                            Extraction Plan
                          </p>
                          <pre className="text-[10px] text-gray-500 overflow-x-auto">
                            {JSON.stringify(message.result.query_plan, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            {message.result.warnings && message.result.warnings.length > 0 && (
              <div className="flex items-start space-x-2 p-3 bg-amber-50 rounded-xl border border-amber-100">
                <AlertCircle className="w-4 h-4 text-amber-500 mt-0.5" />
                <div className="text-xs text-amber-700">
                  {message.result.warnings.map((w, i) => (
                    <p key={i}>{w}</p>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {message.result?.error && (
          <div className="mt-4 flex items-start space-x-2 p-3 bg-red-50 rounded-xl border border-red-100">
            <AlertCircle className="w-4 h-4 text-red-500 mt-0.5" />
            <p className="text-sm text-red-700 font-medium">
              {message.result.error}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
