'use client'

import { cn } from '@/lib/utils'

interface Column<T> {
  key: string
  header: string
  className?: string
  render: (row: T) => React.ReactNode
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  getRowKey: (row: T) => string
  selectedKey?: string | null
  onRowClick?: (row: T) => void
  emptyMessage?: string
  compact?: boolean
  className?: string
}

export function DataTable<T>({
  columns,
  data,
  getRowKey,
  selectedKey,
  onRowClick,
  emptyMessage = 'No data',
  compact = false,
  className,
}: DataTableProps<T>) {
  return (
    <div className={cn('w-full overflow-auto', className)}>
      <table className="w-full text-[12px] border-collapse">
        <thead>
          <tr className="border-b border-border">
            {columns.map((col) => (
              <th
                key={col.key}
                className={cn(
                  'text-left font-medium text-muted-foreground/70 uppercase tracking-wider text-[10px]',
                  compact ? 'px-2.5 py-2' : 'px-3 py-2.5',
                  col.className
                )}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="text-center text-muted-foreground py-8 text-[12px]"
              >
                {emptyMessage}
              </td>
            </tr>
          ) : (
            data.map((row) => {
              const key = getRowKey(row)
              const isSelected = selectedKey === key
              return (
                <tr
                  key={key}
                  onClick={() => onRowClick?.(row)}
                  className={cn(
                    'border-b border-border/50 transition-colors',
                    onRowClick ? 'cursor-pointer' : '',
                    isSelected
                      ? 'bg-primary/8 border-l-2 border-l-primary'
                      : onRowClick
                      ? 'hover:bg-surface-2/60'
                      : ''
                  )}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={cn(
                        'text-foreground/85',
                        compact ? 'px-2.5 py-1.5' : 'px-3 py-2',
                        col.className
                      )}
                    >
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}
