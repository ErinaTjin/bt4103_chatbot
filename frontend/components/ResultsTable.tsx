"use client";
 
import { useMemo, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  getSortedRowModel,
  getFilteredRowModel,
  SortingState,
  ColumnFiltersState,
  ColumnDef,
} from "@tanstack/react-table";
import { DataRow } from "@/lib/types";
import { Search, Download } from "lucide-react";
 
interface ResultsTableProps {
  data: DataRow[];
}
 
export function ResultsTable({ data }: ResultsTableProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [globalFilter, setGlobalFilter] = useState("");
 
  const columns = useMemo<ColumnDef<DataRow>[]>(() => {
    if (!data || data.length === 0) return [];
 
    return Object.keys(data[0]).map((key) => ({
      accessorKey: key,
      header: key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, " "),
      cell: ({ getValue }) => {
        const value = getValue();
        if (typeof value === "number") {
          if (key.includes("percentage")) {
            return `${value.toLocaleString()}%`;
          }
          // Don't format year columns with thousand separators
          if (key.includes("year") || key.includes("date")) {
            return value.toString();
          }
          return value.toLocaleString();
        }
        return value;
      },
    }));
  }, [data]);
 
  const table = useReactTable({
    data,
    columns,
    state: { sorting, columnFilters, globalFilter },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });
 
  if (!data || data.length === 0) return null;
 
  const downloadCSV = () => {
    const headers = Object.keys(data[0]);
    const escape = (val: unknown): string => {
      if (val === null || val === undefined) return "";
      const str = String(val).replace(/"/g, '""');
      return str.includes(",") || str.includes('"') || str.includes("\n")
        ? `"${str}"`
        : str;
    };
    const rows = table.getRowModel().rows.map((row) =>
      headers.map((h) => escape(row.getValue(h))).join(",")
    );
    const csv = [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `results_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };
 
  const filteredCount = table.getRowModel().rows.length;
  const totalCount = data.length;
 
  return (
    <div className="w-full overflow-hidden rounded-xl border border-gray-100 bg-white">
      {/* Search bar + CSV export */}
      <div className="px-4 py-2 border-b border-gray-100 flex items-center space-x-2">
        <Search className="w-3 h-3 text-gray-400 shrink-0" />
        <input
          value={globalFilter}
          onChange={(e) => setGlobalFilter(e.target.value)}
          placeholder="Search all columns..."
          className="w-full text-xs text-gray-600 placeholder-gray-300 outline-none bg-transparent"
        />
        {globalFilter && (
          <span className="text-[10px] text-gray-400 shrink-0">
            {filteredCount}/{totalCount} rows
          </span>
        )}
        <button
          onClick={downloadCSV}
          title="Download table as CSV"
          className="flex items-center gap-1 ml-2 px-2 py-1 rounded-md text-[10px] font-medium text-gray-500 hover:text-blue-600 hover:bg-blue-50 border border-gray-200 hover:border-blue-200 transition-colors shrink-0"
        >
          <Download className="w-3 h-3" />
          CSV
        </button>
      </div>
 
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm border-collapse">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="bg-gray-50/50 border-bottom border-gray-100">
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    className="px-4 py-3 font-semibold text-gray-500 transition-colors hover:text-gray-900 cursor-pointer select-none"
                  >
                    <div className="flex items-center space-x-1">
                      <span>
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                      </span>
                      <span className="w-4 h-4 flex items-center justify-center">
                        {{
                          asc: "↑",
                          desc: "↓",
                        }[header.column.getIsSorted() as string] ?? null}
                      </span>
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-gray-50">
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-6 text-center text-xs text-gray-400"
                >
                  No rows match your search
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className="group transition-colors hover:bg-blue-50/30"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className="px-4 py-3 text-gray-600 group-hover:text-blue-900 transition-colors"
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}