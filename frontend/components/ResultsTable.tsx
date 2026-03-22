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
import { Search } from "lucide-react";

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

  const filteredCount = table.getRowModel().rows.length;
  const totalCount = data.length;

  return (
    <div className="w-full overflow-hidden rounded-xl border border-gray-100 bg-white">
      {/* Global search bar */}
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