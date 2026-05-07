import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  width?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  idKey?: string;
  onRowClick?: (row: T) => void;
  selectedId?: string | number | null;
  isLoading?: boolean;
  emptyMessage?: string;
  compact?: boolean;
}

export function DataTable<T extends Record<string, any>>({
  columns,
  data,
  idKey = "id",
  onRowClick,
  selectedId,
  isLoading,
  emptyMessage = "No data available.",
  compact = false,
}: DataTableProps<T>) {
  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center p-8 gap-3">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-[#e2e8f0] border-t-[#3b82f6]" />
        <p className="text-sm text-[#64748b]">Loading...</p>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
        <p className="text-sm text-[#94a3b8]">{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-[#e2e8f0] overflow-hidden">
      <div className="overflow-x-auto">
        <table className={cn("w-full", compact && "text-xs")}>
          <thead>
            <tr className="border-b border-[#e2e8f0] bg-[#f8fafc]">
              {columns.map((col) => (
                <th
                  key={col.key}
                  className="px-4 py-3 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wider"
                  style={{ width: col.width }}
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#e2e8f0]">
            {data.map((row, idx) => {
              const rowId = row[idKey] ?? idx;
              const isSelected = selectedId !== null && selectedId !== undefined && rowId === selectedId;
              return (
                <tr
                  key={String(rowId)}
                  onClick={() => onRowClick?.(row)}
                  className={cn(
                    "transition-colors",
                    onRowClick && "cursor-pointer hover:bg-[#f8fafc]",
                    isSelected && "bg-[#eff6ff]"
                  )}
                >
                  {columns.map((col) => {
                    const value = col.key.includes(".")
                      ? col.key.split(".").reduce((obj: any, k: string) => obj?.[k], row)
                      : row[col.key];
                    return (
                      <td key={col.key} className="px-4 py-3 text-sm text-[#0f172a]">
                        {col.render ? col.render(row) : String(value ?? "-")}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
