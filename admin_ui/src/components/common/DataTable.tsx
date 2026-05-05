import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => ReactNode;
  sortable?: boolean;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyField: string;
  onRowClick?: (row: T) => void;
  isLoading?: boolean;
  emptyMessage?: string;
  selectedKey?: string | null;
}

export function DataTable<T extends Record<string, any>>({
  columns,
  data,
  keyField,
  onRowClick,
  isLoading,
  emptyMessage = "No data available.",
  selectedKey,
}: DataTableProps<T>) {
  if (isLoading) {
    return <article aria-busy={true}>Loading...</article>;
  }

  if (data.length === 0) {
    return <p style={{ color: "var(--muted-color)" }}>{emptyMessage}</p>;
  }

  return (
    <figure>
      <table>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key}>{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr
              key={row[keyField]}
              onClick={() => onRowClick?.(row)}
              style={{
                cursor: onRowClick ? "pointer" : undefined,
                ...(selectedKey && selectedKey === row[keyField]
                  ? { backgroundColor: "var(--pico-primary-background)", color: "#fff" }
                  : {}),
              }}
              aria-selected={selectedKey === row[keyField] ? true : undefined}
            >
              {columns.map((col) => (
                <td key={col.key}>
                  {col.render ? col.render(row) : row[col.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
