"use client";
 
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { getAdminLogs } from "@/lib/api";
import { AuditLog } from "@/lib/types";
import { VegaEmbed } from "react-vega";
import { RefreshCw, AlertCircle, ShieldAlert, Activity, Table2, LogOut, Download } from "lucide-react";
 
// ── helpers ───────────────────────────────────────────────────────────────────
 
function parseJsonField(raw: string | null): string[] {
  if (!raw) return [];
  try { return JSON.parse(raw); } catch { return []; }
}
 
// ── chart specs ───────────────────────────────────────────────────────────────
 
function latencySpec(rows: { index: number; sec: number; time: string }[]): Record<string, unknown> {
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    data: { values: rows },
    width: "container",
    height: 220,
    mark: { type: "line", point: true, color: "#6366f1" },
    encoding: {
      x: { field: "index", type: "quantitative", title: "Query #", axis: { tickMinStep: 1 } },
      y: { field: "sec", type: "quantitative", title: "Latency (s)" },
      tooltip: [
        { field: "index", type: "quantitative", title: "Query #" },
        { field: "sec", type: "quantitative", title: "Latency (s)" },
        { field: "time", type: "temporal", title: "Time" },
      ],
    },
  };
}
 
function blockedSpec(rows: { reason: string; count: number }[]): Record<string, unknown> {
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    data: { values: rows },
    width: "container",
    height: 220,
    mark: { type: "bar", color: "#f43f5e" },
    encoding: {
      x: { field: "reason", type: "nominal", title: "Reason", sort: "-y", axis: { labelAngle: -20 } },
      y: { field: "count", type: "quantitative", title: "Count" },
      tooltip: [
        { field: "reason", type: "nominal", title: "Reason" },
        { field: "count", type: "quantitative", title: "Count" },
      ],
    },
  };
}
 
// ── main component ────────────────────────────────────────────────────────────
 
export default function AdminDashboard() {
  const { user, isAdmin, loading, logout } = useAuth();
  const router = useRouter();
 
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
 
  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);
 
  const fetchLogs = useCallback(async () => {
    setFetching(true);
    setError(null);
    try {
      const data = await getAdminLogs(200);
      setLogs(data);
      setLastRefreshed(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load logs");
    } finally {
      setFetching(false);
    }
  }, []);
 
  useEffect(() => {
    if (isAdmin) fetchLogs();
  }, [isAdmin, fetchLogs]);
 
  if (loading || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950 text-gray-400">
        Loading…
      </div>
    );
  }
 
  if (!isAdmin) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950">
        <div className="flex flex-col items-center gap-4 text-center p-8 rounded-xl bg-gray-900 border border-gray-800 max-w-sm w-full">
          <ShieldAlert size={48} className="text-red-500" />
          <h1 className="text-2xl font-bold text-gray-100">403 Forbidden</h1>
          <p className="text-gray-400 text-sm">
            You don&apos;t have permission to access this page.
          </p>
          <button
            onClick={() => router.push("/chat")}
            className="mt-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-colors"
          >
            Back to Chat
          </button>
        </div>
      </div>
    );
  }
 
  // ── CSV export ──────────────────────────────────────────────────────────────
  const downloadCSV = () => {
    const headers = [
      "id", "timestamp", "username", "session_id",
      "nl_question", "resolved_question", "generated_sql",
      "latency_s", "row_count", "guardrail_decision",
      "guardrail_reasons", "warnings", "error_message",
    ];
 
    const escape = (val: unknown): string => {
      if (val === null || val === undefined) return "";
      const str = String(val).replace(/"/g, '""');
      return str.includes(",") || str.includes('"') || str.includes("\n")
        ? `"${str}"`
        : str;
    };
 
    const rows = logs.map((l) => [
      l.id,
      l.timestamp,
      l.username ?? "",
      l.session_id ?? "",
      l.nl_question ?? "",
      l.resolved_question ?? "",
      l.generated_sql ?? "",
      l.execution_ms !== null ? (l.execution_ms / 1000).toFixed(2) : "",
      l.row_count ?? "",
      l.guardrail_decision,
      l.guardrail_reasons,
      l.warnings,
      l.error_message ?? "",
    ].map(escape).join(","));
 
    const csv = [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `anchor_query_log_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };
 
  // ── derived data ────────────────────────────────────────────────────────────
 
  const filteredLatency = logs.filter((l) => l.execution_ms !== null).reverse();
  const latencyRows = filteredLatency.map((l, i) => ({
    index: i + 1,
    sec: (l.execution_ms as number) / 1000,
    time: l.timestamp,
  }));
 
  const reasonCounts: Record<string, number> = {};
  logs
    .filter((l) => l.guardrail_decision === "block")
    .forEach((l) => {
      const reasons = parseJsonField(l.guardrail_reasons);
      const label = reasons.length > 0 ? reasons[0].slice(0, 60) : "unknown";
      reasonCounts[label] = (reasonCounts[label] ?? 0) + 1;
    });
  const blockedRows = Object.entries(reasonCounts)
    .map(([reason, count]) => ({ reason, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);
 
  const errorLogs = logs.filter((l) => l.error_message || l.guardrail_decision === "error");
  const totalQueries = logs.length;
  const blockedCount = logs.filter((l) => l.guardrail_decision === "block").length;
  const avgLatency =
    latencyRows.length > 0
      ? latencyRows.reduce((s, r) => s + r.sec, 0) / latencyRows.length
      : null;
 
  // ── render ──────────────────────────────────────────────────────────────────
 
  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
        <div className="flex items-center gap-3">
          <ShieldAlert className="text-indigo-400" size={22} />
          <span className="font-semibold text-lg">Admin Dashboard</span>
        </div>
        <div className="flex items-center gap-3">
          {lastRefreshed && (
            <span className="text-xs text-gray-500">
              Last updated {lastRefreshed.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchLogs}
            disabled={fetching}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm transition-colors"
          >
            <RefreshCw size={14} className={fetching ? "animate-spin" : ""} />
            Refresh
          </button>
          <button
            onClick={() => router.push("/chat")}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-sm transition-colors"
          >
            Chat
          </button>
          <button
            onClick={async () => { await logout(); router.replace("/login"); }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-sm transition-colors"
          >
            <LogOut size={14} />
            Sign out
          </button>
        </div>
      </header>
 
      <main className="p-6 space-y-6 max-w-screen-xl mx-auto">
        {error && (
          <div className="flex items-center gap-2 p-4 rounded-lg bg-red-950 border border-red-700 text-red-300 text-sm">
            <AlertCircle size={16} />
            {error}
          </div>
        )}
 
        {/* KPI cards */}
        <div className="grid grid-cols-3 gap-4">
          <StatCard label="Total Queries" value={totalQueries} icon={<Activity size={18} />} />
          <StatCard
            label="Blocked Queries"
            value={blockedCount}
            icon={<ShieldAlert size={18} />}
            accent="red"
          />
          <StatCard
            label="Avg Latency"
            value={avgLatency !== null ? `${avgLatency.toFixed(2)}s` : "—"}
            icon={<RefreshCw size={18} />}
            accent="indigo"
          />
        </div>
 
        {/* Charts row */}
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-xl bg-gray-900 border border-gray-800 p-4">
            <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
              <Activity size={15} className="text-indigo-400" />
              Latency Over Time
            </h2>
            {latencyRows.length === 0 ? (
              <EmptyState text="No latency data yet" />
            ) : (
              <VegaEmbed spec={latencySpec(latencyRows)} options={{ actions: false }} style={{ width: "100%" }} />
            )}
          </div>
 
          <div className="rounded-xl bg-gray-900 border border-gray-800 p-4">
            <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
              <ShieldAlert size={15} className="text-rose-400" />
              Blocked Queries by Reason
            </h2>
            {blockedRows.length === 0 ? (
              <EmptyState text="No blocked queries" />
            ) : (
              <VegaEmbed spec={blockedSpec(blockedRows)} options={{ actions: false }} style={{ width: "100%" }} />
            )}
          </div>
        </div>
 
        {/* Recent errors */}
        <div className="rounded-xl bg-gray-900 border border-gray-800 p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
            <AlertCircle size={15} className="text-amber-400" />
            Recent Errors
          </h2>
          {errorLogs.length === 0 ? (
            <EmptyState text="No errors recorded" />
          ) : (
            <div className="overflow-auto max-h-64">
              <table className="w-full text-xs text-left text-gray-300">
                <thead className="sticky top-0 bg-gray-900 text-gray-500 uppercase">
                  <tr>
                    <th className="pb-2 pr-4 font-medium">Time</th>
                    <th className="pb-2 pr-4 font-medium">User</th>
                    <th className="pb-2 pr-4 font-medium">Question</th>
                    <th className="pb-2 font-medium">Error</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800">
                  {errorLogs.slice(0, 50).map((l) => (
                    <tr key={l.id} className="hover:bg-gray-800/50">
                      <td className="py-1.5 pr-4 whitespace-nowrap text-gray-500">
                        {new Date(l.timestamp).toLocaleString()}
                      </td>
                      <td className="py-1.5 pr-4 whitespace-nowrap">{l.username ?? "—"}</td>
                      <td className="py-1.5 pr-4 max-w-xs truncate" title={l.nl_question ?? ""}>
                        {l.nl_question ?? "—"}
                      </td>
                      <td className="py-1.5 text-red-400 max-w-sm truncate" title={l.error_message ?? ""}>
                        {l.error_message}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
 
        {/* Full query log */}
        <div className="rounded-xl bg-gray-900 border border-gray-800 p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
              <Table2 size={15} className="text-gray-400" />
              Query Log ({logs.length})
            </h2>
            {logs.length > 0 && (
              <button
                onClick={downloadCSV}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-xs text-gray-300 transition-colors"
              >
                <Download size={13} />
                Download CSV
              </button>
            )}
          </div>
          {logs.length === 0 ? (
            <EmptyState text="No queries recorded" />
          ) : (
            <div className="overflow-auto max-h-96">
              <table className="w-full text-xs text-left text-gray-300">
                <thead className="sticky top-0 bg-gray-900 text-gray-500 uppercase">
                  <tr>
                    <th className="pb-2 pr-3 font-medium">Query #</th>
                    <th className="pb-2 pr-3 font-medium">Time</th>
                    <th className="pb-2 pr-3 font-medium">User</th>
                    <th className="pb-2 pr-3 font-medium">Question</th>
                    <th className="pb-2 pr-3 font-medium">Status</th>
                    <th className="pb-2 pr-3 font-medium">Latency</th>
                    <th className="pb-2 font-medium">Rows</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800">
                  {logs.map((l, index) => (
                    <tr key={l.id} className="hover:bg-gray-800/50">
                      <td className="py-1.5 pr-3 whitespace-nowrap text-gray-400 font-medium">
                        #{logs.length - index}
                      </td>
                      <td className="py-1.5 pr-3 whitespace-nowrap text-gray-500">
                        {new Date(l.timestamp).toLocaleString()}
                      </td>
                      <td className="py-1.5 pr-3 whitespace-nowrap">{l.username ?? "—"}</td>
                      <td className="py-1.5 pr-3 max-w-xs truncate" title={l.nl_question ?? ""}>
                        {l.nl_question ?? "—"}
                      </td>
                      <td className="py-1.5 pr-3">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                            l.guardrail_decision === "block"
                              ? "bg-red-900 text-red-300"
                              : l.guardrail_decision === "clarification"
                              ? "bg-amber-900 text-amber-300"
                              : l.guardrail_decision === "error"
                              ? "bg-orange-900 text-orange-300"
                              : "bg-green-900 text-green-300"
                          }`}
                        >
                          {l.guardrail_decision}
                        </span>
                      </td>
                      <td className="py-1.5 pr-3 text-right">
                        {l.execution_ms !== null ? `${(l.execution_ms / 1000).toFixed(2)}s` : "—"}
                      </td>
                      <td className="py-1.5 text-right">
                        {l.row_count !== null ? l.row_count : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
 
// ── sub-components ─────────────────────────────────────────────────────────────
 
function StatCard({
  label,
  value,
  icon,
  accent = "gray",
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  accent?: "gray" | "red" | "indigo";
}) {
  const accentClass =
    accent === "red"
      ? "text-red-400"
      : accent === "indigo"
      ? "text-indigo-400"
      : "text-gray-400";
  return (
    <div className="rounded-xl bg-gray-900 border border-gray-800 p-4 flex items-center gap-4">
      <div className={`${accentClass}`}>{icon}</div>
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
        <p className="text-2xl font-bold mt-0.5">{value}</p>
      </div>
    </div>
  );
}
 
function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex items-center justify-center h-24 text-gray-600 text-sm">{text}</div>
  );
}