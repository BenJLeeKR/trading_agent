import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { OrderSummary } from "../types/api";
import { getOrders } from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import type { Column } from "./common/DataTable";

const ORDER_STATUSES = [
  "all",
  "pending",
  "submitted",
  "partial",
  "filled",
  "rejected",
  "cancelled",
] as const;

const SIDES = ["all", "buy", "sell", "hold"] as const;

export default function OrdersView() {
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sideFilter, setSideFilter] = useState("all");
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    setError(null);
    getOrders()
      .then(setOrders)
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Failed to load orders";
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, []);

  const filteredOrders = useMemo(() => {
    return orders.filter((o) => {
      if (searchText && !o.symbol.toLowerCase().includes(searchText.toLowerCase())) {
        return false;
      }
      if (statusFilter !== "all" && o.status !== statusFilter) {
        return false;
      }
      if (sideFilter !== "all" && o.side !== sideFilter) {
        return false;
      }
      return true;
    });
  }, [orders, searchText, statusFilter, sideFilter]);

  const columns: Column<OrderSummary>[] = [
    { key: "created_at", label: "Created" },
    { key: "symbol", label: "Symbol" },
    {
      key: "side",
      label: "Side",
      render: (r) => (
        <span
          style={{
            color:
              r.side.toLowerCase() === "buy"
                ? "var(--status-success)"
                : "var(--status-error)",
            fontWeight: 600,
          }}
        >
          {r.side.toUpperCase()}
        </span>
      ),
    },
    { key: "order_type", label: "Type" },
    { key: "qty", label: "Qty" },
    {
      key: "status",
      label: "Status",
      render: (r) => <StatusBadge status={r.status} />,
    },
    { key: "strategy_code", label: "Strategy" },
  ];

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  return (
    <section>
      <div className="page-header">
        <h2>Orders</h2>
        <p>
          Total: {filteredOrders.length} / {orders.length} order
          {orders.length !== 1 ? "s" : ""}
        </p>
      </div>

      <div className="filter-bar">
        <input
          type="search"
          placeholder="Search by symbol…"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          style={{ flex: 1, minWidth: "180px" }}
          aria-label="Search by symbol"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by status"
          style={{ minWidth: "130px" }}
        >
          {ORDER_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s === "all" ? "All Statuses" : s.charAt(0).toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
        <select
          value={sideFilter}
          onChange={(e) => setSideFilter(e.target.value)}
          aria-label="Filter by side"
          style={{ minWidth: "100px" }}
        >
          {SIDES.map((s) => (
            <option key={s} value={s}>
              {s === "all" ? "All Sides" : s.charAt(0).toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
      </div>

      <DataTable
        columns={columns}
        data={filteredOrders}
        keyField="order_request_id"
        onRowClick={(row) => navigate(`/orders/${row.order_request_id}`)}
        emptyMessage="No orders found."
      />
    </section>
  );
}
