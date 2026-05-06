import { cn } from "@/lib/utils"

interface Column<T> {
  key: keyof T | string
  header: string
  render?: (value: any, row: T) => React.ReactNode
  width?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  onRowClick?: (row: T) => void
  selectedId?: string | number
  idKey?: keyof T
}

export function DataTable<T extends Record<string, any>>({
  columns,
  data,
  onRowClick,
  selectedId,
  idKey = "id" as keyof T,
}: DataTableProps<T>) {
  return (
    <div className="bg-white rounded-xl border border-[#e2e8f0] overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#e2e8f0] bg-[#f8fafc]">
              {columns.map((col) => (
                <th
                  key={String(col.key)}
                  className="px-4 py-3 text-left text-xs font-medium text-[#64748b] uppercase tracking-wider"
                  style={{ width: col.width }}
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#e2e8f0]">
            {data.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-8 text-center text-sm text-[#94a3b8]"
                >
                  No data available
                </td>
              </tr>
            ) : (
              data.map((row, idx) => {
                const isSelected = selectedId !== undefined && row[idKey] === selectedId
                return (
                  <tr
                    key={row[idKey] ?? idx}
                    onClick={() => onRowClick?.(row)}
                    className={cn(
                      "transition-colors",
                      onRowClick && "cursor-pointer hover:bg-[#f8fafc]",
                      isSelected && "bg-[#eff6ff]"
                    )}
                  >
                    {columns.map((col) => {
                      const value = col.key.toString().includes(".")
                        ? col.key.toString().split(".").reduce((obj, key) => obj?.[key], row)
                        : row[col.key as keyof T]
                      return (
                        <td key={String(col.key)} className="px-4 py-3 text-sm text-[#0f172a]">
                          {col.render ? col.render(value, row) : String(value ?? "-")}
                        </td>
                      )
                    })}
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
