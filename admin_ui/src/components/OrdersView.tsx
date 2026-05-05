import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { OrderSummary } from "../types/api";
import { getOrders } from "../api/client";
import { DataTable } from "./common/DataTable";
import { Panel } from "./common/Panel";
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

/* ───────────────────────────────────────────
 * FilterGroup — single-select button group
 * ─────────────────────────────────────────── */
function FilterGroup({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { label: string; value: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="filter-group" role="group" aria-label={label}>
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`filter-group-btn${value === opt.value ? " filter-group-btn--active" : ""}`}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

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
        <span className={r.side.toLowerCase() === "buy" ? "side-buy" : "side-sell"}>
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
      <div className="filter-bar">
        <input
          type="search"
          placeholder="Search by symbol…"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          className="filter-input-flex"
          aria-label="Search by symbol"
        />

        <FilterGroup
          label="Status"
          options={ORDER_STATUSES.map((s) => ({
            label: s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1),
            value: s,
          }))}
          value={statusFilter}
          onChange={setStatusFilter}
        />

        <FilterGroup
          label="Side"
          options={SIDES.map((s) => ({
            label: s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1),
            value: s,
          }))}
          value={sideFilter}
          onChange={setSideFilter}
        />
      </div>

      <Panel
        title="Orders"
        headerRight={
          <span className="panel-counter">
            Total: {filteredOrders.length} / {orders.length} order
            {orders.length !== 1 ? "s" : ""}
          </span>
        }
      >
        <DataTable
          columns={columns}
          data={filteredOrders}
          keyField="order_request_id"
          onRowClick={(row) => navigate(`/orders/${row.order_request_id}`)}
          emptyMessage="No orders found."
          compact
        />
      </Panel>
    </section>
  );
}
