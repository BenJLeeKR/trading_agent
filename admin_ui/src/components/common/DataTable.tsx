import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { ChevronLeft, ChevronRight } from "lucide-react";

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  width?: string;
  align?: "left" | "right" | "center";
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

  /** Optional per-row class name — receives the row data, returns a CSS class string */
  rowClassName?: (row: T) => string;

  // Pagination props (optional — when provided, show footer)
  currentPage?: number;
  pageSize?: number;
  totalItems?: number;
  onPageChange?: (page: number) => void;
  onPageSizeChange?: (pageSize: number) => void;
  pageSizeOptions?: number[];
}

/* ── Page number helper ── */
function getPageNumbers(current: number, total: number): (number | "ellipsis")[] {
  const sideWindow = 3;
  if (total <= sideWindow * 2 + 3) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }

  const pages: (number | "ellipsis")[] = [1];

  if (current > sideWindow + 2) {
    pages.push("ellipsis");
  }

  const start = Math.max(2, current - sideWindow);
  const end = Math.min(total - 1, current + sideWindow);

  for (let i = start; i <= end; i++) {
    pages.push(i);
  }

  if (current < total - (sideWindow + 1)) {
    pages.push("ellipsis");
  }

  pages.push(total);

  return pages;
}

export function DataTable<T extends Record<string, any>>({
  columns,
  data,
  idKey = "id",
  onRowClick,
  selectedId,
  isLoading,
  emptyMessage = "데이터가 없습니다.",
  compact = false,
  rowClassName,
  currentPage,
  pageSize = 20,
  totalItems,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [10, 20, 50],
}: DataTableProps<T>) {
  const alignmentClass = (align?: "left" | "right" | "center") => {
    switch (align) {
      case "right":
        return "text-right";
      case "center":
        return "text-center";
      default:
        return "text-left";
    }
  };

  if (isLoading && data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-8 gap-3">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-[#e2e8f0] border-t-[#3b82f6]" />
        <p className="text-sm text-[#64748b]">로딩 중...</p>
      </div>
    );
  }

  if (!isLoading && data.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
        <p className="text-sm text-[#94a3b8]">{emptyMessage}</p>
      </div>
    );
  }

  const showPagination =
    currentPage !== undefined &&
    totalItems !== undefined &&
    onPageChange !== undefined;

  const totalPages = Math.max(1, Math.ceil(totalItems! / pageSize));

  return (
    <div className="bg-white rounded-xl border border-[#e2e8f0] overflow-hidden">
      {/* 로딩 중 오버레이 인디케이터 (데이터 유지) */}
      {isLoading && data.length > 0 && (
        <div className="flex items-center justify-center gap-2 py-2 bg-[#f8fafc] border-b border-[#e2e8f0]">
          <div className="h-3 w-3 animate-spin rounded-full border-2 border-[#e2e8f0] border-t-[#3b82f6]" />
          <span className="text-xs text-[#64748b]">로딩 중...</span>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className={cn("w-full", compact && "text-xs")}>
          <thead>
            <tr className="border-b border-[#e2e8f0] bg-[#f8fafc]">
              {columns.map((col) => (
                <th
                  key={col.key}
                  className="px-4 py-3 text-center text-xs font-semibold text-[#64748b] uppercase tracking-wider"
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
                    isSelected && "bg-[#eff6ff]",
                    rowClassName?.(row)
                  )}
                >
                  {columns.map((col) => {
                    const value = col.key.includes(".")
                      ? col.key.split(".").reduce((obj: any, k: string) => obj?.[k], row)
                      : row[col.key];
                    return (
                      <td
                        key={col.key}
                        className={cn("px-4 py-3 text-sm text-[#0f172a]", alignmentClass(col.align))}
                      >
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

      {/* Pagination footer */}
      {showPagination && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-[#e2e8f0]">
          {/* Left: total count */}
          <span className="text-xs text-[#94a3b8]">총 {totalItems}건</span>

          {/* Right: page navigation + page-size selector */}
          <div className="flex items-center gap-3">
            {/* Page navigation */}
            <div className="flex items-center gap-1">
              <button
                onClick={() => onPageChange!(Math.max(1, currentPage! - 1))}
                disabled={currentPage === 1}
                className="p-1 rounded border border-[#e2e8f0] text-[#64748b] hover:bg-[#f1f5f9] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                aria-label="Previous page"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>

              {getPageNumbers(currentPage!, totalPages).map((page, i) =>
                page === "ellipsis" ? (
                  <span key={`ellipsis-${i}`} className="px-1 text-xs text-[#94a3b8]">
                    ...
                  </span>
                ) : (
                  <button
                    key={page}
                    onClick={() => onPageChange!(page)}
                    className={cn(
                      "min-w-[28px] h-[28px] rounded border text-xs font-medium transition-colors",
                      page === currentPage
                        ? "bg-[#3b82f6] border-[#3b82f6] text-white"
                        : "border-[#e2e8f0] text-[#64748b] hover:bg-[#f1f5f9]"
                    )}
                  >
                    {page}
                  </button>
                )
              )}

              <button
                onClick={() => onPageChange!(Math.min(totalPages, currentPage! + 1))}
                disabled={currentPage === totalPages}
                className="p-1 rounded border border-[#e2e8f0] text-[#64748b] hover:bg-[#f1f5f9] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                aria-label="Next page"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>

            {/* Page-size selector */}
            {onPageSizeChange && (
              <select
                value={pageSize}
                onChange={(e) => onPageSizeChange(Number(e.target.value))}
                className="h-[28px] rounded border border-[#e2e8f0] bg-white px-2 text-xs text-[#374151] focus:outline-none focus:ring-1 focus:ring-[#3b82f6] cursor-pointer"
              >
                {pageSizeOptions.map((n) => (
                  <option key={n} value={n}>
                    {n}건씩 보기
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
