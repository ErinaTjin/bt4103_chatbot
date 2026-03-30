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
  Brain,
  Info,
} from "lucide-react";
import { useEffect, useState } from "react";

interface MessageBubbleProps {
  message: Message;
  isUser?: boolean;
  debugMode?: boolean;
}

export function MessageBubble({
  message,
  isUser = false,
  debugMode = false,
}: MessageBubbleProps) {
  const [showSql, setShowSql] = useState(false);
  const [showReasoning, setShowReasoning] = useState(false);
  const [showRawPlan, setShowRawPlan] = useState(false);
  const [chartType, setChartType] = useState<string | null>(null);

  const visualization =
    message.result?.query_plan?.output?.preferred_visualization;
  const showChart =
    visualization &&
    visualization !== "table" &&
    (message.result?.data?.length ?? 0) > 0;

  // Determine all valid chart types based on data shape (including current)
  const getValidChartTypes = (data: any[]) => {
    if (!data || data.length === 0) return [] as string[];

    const keys = Object.keys(data[0]);
    const numeric = keys.filter((k) => typeof data[0][k] === "number");
    const dims = keys.filter((k) => typeof data[0][k] !== "number");

    const isTime = dims.some((k) => k.includes("year") || k.includes("date"));

    const options: string[] = [];

    if (numeric.length >= 1 && dims.length >= 1) options.push("bar");
    if (numeric.length === 1 && dims.length === 1) options.push("pie");
    if (isTime && numeric.length >= 1) options.push("line");

    return options;
  };

  const validTypes = getValidChartTypes(message.result?.data || []);

  // Initialize chart type from backend recommendation
  useEffect(() => {
    if (visualization) {
      setChartType(visualization);
    }
  }, [visualization]);

  const summary =
    message.result?.data && message.result?.query_plan?.intent
      ? generateSummary(
          message.result.data,
          message.result.query_plan.intent,
          message.content,
        )
      : null;

  // Extract human-readable reasoning fields from Agent 2's output
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const agent2 = message.result?.plan_agent2 as Record<string, any> | undefined;
  const reasoningSummary = agent2?.reasoning_summary as string | undefined;
  const assumptions = agent2?.assumptions as string[] | undefined;
  const hasReasoning =
    reasoningSummary || (assumptions && assumptions.length > 0);

  const warnings = message.result?.warnings ?? [];
  const formattedTime = new Date(message.timestamp).toLocaleTimeString();

  // Simple SQL formatter for readability in debug view
  const formatSQL = (sql: string) => {
    if (!sql) return "";
    return sql
      .replace(/\s+/g, " ")
      .replace(/\bSELECT\b/gi, "\nSELECT")
      .replace(/\bFROM\b/gi, "\nFROM")
      .replace(/\bWHERE\b/gi, "\nWHERE")
      .replace(/\bGROUP BY\b/gi, "\nGROUP BY")
      .replace(/\bORDER BY\b/gi, "\nORDER BY")
      .replace(/\bHAVING\b/gi, "\nHAVING")
      .replace(/\bLIMIT\b/gi, "\nLIMIT")
      .replace(/\bJOIN\b/gi, "\nJOIN")
      .replace(/\bLEFT JOIN\b/gi, "\nLEFT JOIN")
      .replace(/\bRIGHT JOIN\b/gi, "\nRIGHT JOIN")
      .replace(/\bINNER JOIN\b/gi, "\nINNER JOIN")
      .trim();
  };

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
        <p
          className={`mt-2 text-[10px] ${isUser ? "text-blue-100" : "text-gray-400"}`}
        >
          {formattedTime}
        </p>

        {/* Agent 0 interpretation — only shown when question was rewritten */}
        {!isUser &&
          message.result?.resolved_question &&
          message.result.resolved_question !== message.content && (
            <details className="mt-2 group">
              <summary className="text-[10px] text-gray-400 cursor-pointer hover:text-gray-600 select-none list-none flex items-center gap-1 w-fit">
                <ChevronDown className="w-2.5 h-2.5 transition-transform group-open:rotate-180" />
                interpreted as
              </summary>
              <p className="mt-1.5 text-xs text-gray-500 italic pl-3 border-l-2 border-gray-200 leading-relaxed">
                "{message.result.resolved_question}"
              </p>
            </details>
          )}

        {message.result && !message.result.error && (
          <div className="mt-6 space-y-4">
            {summary && <SummaryCard summary={summary} />}

            {showChart ? (
              <div className="space-y-4">
                {/* Chart selector: show all valid types (including current) */}
                {validTypes.length > 0 && chartType && (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-500">
                      Visualization:
                    </span>
                    <select
                      value={chartType}
                      onChange={(e) => setChartType(e.target.value)}
                      className="text-xs border rounded px-2 py-1 bg-white"
                    >
                      {validTypes.map((type) => (
                        <option key={type} value={type}>
                          {type.toUpperCase()}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <ResultsChart
                  data={message.result.data}
                  type={chartType || visualization}
                />
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

            {/* Debug section — only visible when debugMode is on */}
            {debugMode && (
              <div className="pt-2 border-t border-gray-100 space-y-3">
                {/* SQL toggle */}
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
                          <div className="absolute top-2 right-2">
                            <Database className="w-3 h-3 text-gray-500" />
                          </div>
                          <pre className="p-4 bg-gray-900 text-blue-300 rounded-xl text-[11px] font-mono leading-relaxed overflow-x-auto border border-gray-800 whitespace-pre-wrap">
                            {formatSQL(message.result.sql)}
                          </pre>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Model Reasoning — human-readable card */}
                {hasReasoning && (
                  <div>
                    <button
                      onClick={() => setShowReasoning(!showReasoning)}
                      className={`flex items-center text-[10px] uppercase tracking-widest font-bold transition-colors ${
                        isUser
                          ? "text-blue-100 hover:text-white"
                          : "text-gray-400 hover:text-purple-600"
                      }`}
                    >
                      {showReasoning ? (
                        <ChevronUp className="w-3 h-3 mr-1" />
                      ) : (
                        <ChevronDown className="w-3 h-3 mr-1" />
                      )}
                      {showReasoning ? "Hide" : "View"} Model Reasoning
                    </button>
                    {showReasoning && (
                      <div className="mt-3 space-y-3 animate-in zoom-in-95 duration-200">
                        {/* Reasoning summary */}
                        {reasoningSummary && (
                          <div className="p-3 bg-purple-50/60 rounded-xl border border-purple-100">
                            <p className="text-[10px] text-purple-500 uppercase tracking-widest font-bold mb-2 flex items-center">
                              <Brain className="w-3 h-3 mr-1" /> Reasoning
                            </p>
                            <p className="text-xs text-gray-700 leading-relaxed">
                              {reasoningSummary}
                            </p>
                          </div>
                        )}

                        {/* Assumptions */}
                        {assumptions && assumptions.length > 0 && (
                          <div className="p-3 bg-blue-50/60 rounded-xl border border-blue-100">
                            <p className="text-[10px] text-blue-500 uppercase tracking-widest font-bold mb-2 flex items-center">
                              <Info className="w-3 h-3 mr-1" /> Assumptions
                            </p>
                            <ul className="space-y-1">
                              {assumptions.map((a, i) => (
                                <li
                                  key={i}
                                  className="text-xs text-gray-700 flex items-start gap-1.5"
                                >
                                  <span className="text-blue-400 mt-0.5">
                                    •
                                  </span>
                                  {a}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {/* Warnings */}
                        {warnings.length > 0 && (
                          <div className="p-3 bg-amber-50 rounded-xl border border-amber-100">
                            <p className="text-[10px] text-amber-500 uppercase tracking-widest font-bold mb-2 flex items-center">
                              <AlertCircle className="w-3 h-3 mr-1" /> Warnings
                            </p>
                            <ul className="space-y-1">
                              {warnings.map((w, i) => (
                                <li
                                  key={i}
                                  className="text-xs text-amber-700 flex items-start gap-1.5"
                                >
                                  <span className="mt-0.5">•</span>
                                  {w}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Raw agent plans — for advanced debugging */}
                {(message.result.plan_agent1 ||
                  message.result.plan_agent2 ||
                  message.result.query_plan) && (
                  <div>
                    <button
                      onClick={() => setShowRawPlan(!showRawPlan)}
                      className={`flex items-center text-[10px] uppercase tracking-widest font-bold transition-colors ${
                        isUser
                          ? "text-blue-100 hover:text-white"
                          : "text-gray-400 hover:text-blue-600"
                      }`}
                    >
                      {showRawPlan ? (
                        <ChevronUp className="w-3 h-3 mr-1" />
                      ) : (
                        <ChevronDown className="w-3 h-3 mr-1" />
                      )}
                      {showRawPlan ? "Hide" : "View"} Raw Agent Plans
                    </button>
                    {showRawPlan && (
                      <div className="mt-3 space-y-3 animate-in zoom-in-95 duration-200">
                        {message.result.plan_agent1 && (
                          <div className="p-3 bg-blue-50/50 rounded-xl border border-blue-100/50">
                            <p className="text-[10px] text-blue-500 uppercase tracking-widest font-bold mb-2 flex items-center">
                              <FileJson className="w-3 h-3 mr-1" /> Agent 1:
                              Context Plan
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
                              <FileJson className="w-3 h-3 mr-1" /> Agent 2: SQL
                              Writer Plan
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
                              <FileJson className="w-3 h-3 mr-1" /> Final Query
                              Plan
                            </p>
                            <pre className="text-[10px] text-gray-500 overflow-x-auto">
                              {JSON.stringify(
                                message.result.query_plan,
                                null,
                                2,
                              )}
                            </pre>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
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
