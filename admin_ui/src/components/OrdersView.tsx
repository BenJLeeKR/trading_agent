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
import {
  Search,
  X,
  ChevronRight,
  Clock,
  CheckCircle,
  XCircle,
  Minus,
  ExternalLink,
} from "lucide-react";

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

/* ── DetailRow (template pattern) ── */
function DetailRow({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="detail-row">
      <span className="detail-row-label">{label}</span>
      <span
        className="detail-row-value"
        style={{ color: valueColor ?? "var(--text-primary)" }}
      >
        {value}
      </span>
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
  const [selectedOrder, setSelectedOrder] = useState<OrderSummary | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    setError(null);
    getOrders()
      .then(setOrders)
      .catch((err: unknown) => {
        const msg =
          err instanceof Error ? err.message : "Failed to load orders";
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, []);

  const filteredOrders = useMemo(() => {
    return orders.filter((o) => {
      if (
        searchText &&
        !o.symbol.toLowerCase().includes(searchText.toLowerCase())
      ) {
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
          className={
            r.side.toLowerCase() === "buy" ? "side-buy" : "side-sell"
          }
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
  if (error)
    return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  return (
    <section>
      <div className="split-layout">
        {/* Left: filter bar + table */}
        <div className="split-main">
          {/* Filter bar (template pattern) */}
          <div className="filter-bar">
            <div className="filter-input-wrap">
              <Search size={12} className="filter-input-icon" />
              <input
                type="search"
                placeholder="Search by symbol…"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                className="filter-input-flex"
                aria-label="Search by symbol"
              />
              {searchText && (
                <button
                  onClick={() => setSearchText("")}
                  className="filter-input-clear"
                >
                  <X size={11} />
                </button>
              )}
            </div>

            <div className="filter-group" role="group" aria-label="Status">
              {ORDER_STATUSES.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`filter-group-btn${statusFilter === s ? " filter-group-btn--active" : ""}`}
                  onClick={() => setStatusFilter(s)}
                >
                  {s === "all"
                    ? "All"
                    : s.charAt(0).toUpperCase() + s.slice(1)}
                </button>
              ))}
            </div>

            <div className="filter-group" role="group" aria-label="Side">
              {SIDES.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`filter-group-btn${sideFilter === s ? " filter-group-btn--active" : ""}`}
                  onClick={() => setSideFilter(s)}
                >
                  {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Table */}
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
              onRowClick={(row) =>
                setSelectedOrder(
                  selectedOrder?.order_request_id === row.order_request_id
                    ? null
                    : row,
                )
              }
              emptyMessage="No orders found."
              compact
            />
          </Panel>
        </div>

        {/* Right: inline detail panel (template pattern) */}
        {selectedOrder && (
          <div className="detail-side-panel">
            {/* Order Detail card */}
            <div className="card-panel">
              <div className="card-panel-header">
                <span className="card-panel-title">Order Detail</span>
                <button
                  onClick={() => setSelectedOrder(null)}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: "var(--text-muted)",
                    padding: 0,
                  }}
                >
                  <X size={13} />
                </button>
              </div>

              {/* Status banner */}
              <div
                className="status-banner"
                style={{
                  backgroundColor:
                    selectedOrder.status === "filled" ||
                    selectedOrder.status === "partial"
                      ? "#f0fdf4"
                      : selectedOrder.status === "pending" ||
                          selectedOrder.status === "submitted"
                        ? "#fffbeb"
                        : selectedOrder.status === "rejected" ||
                            selectedOrder.status === "cancelled"
                          ? "#fef2f2"
                          : "#eff6ff",
                }}
              >
                <span
                  className="status-banner-dot"
                  style={{
                    backgroundColor:
                      selectedOrder.status === "filled" ||
                      selectedOrder.status === "partial"
                        ? "#22c55e"
                        : selectedOrder.status === "pending" ||
                            selectedOrder.status === "submitted"
                          ? "#f59e0b"
                          : selectedOrder.status === "rejected" ||
                              selectedOrder.status === "cancelled"
                            ? "#ef4444"
                            : "#3b82f6",
                  }}
                />
                <span
                  className="status-banner-label"
                  style={{
                    color:
                      selectedOrder.status === "filled" ||
                      selectedOrder.status === "partial"
                        ? "#16a34a"
                        : selectedOrder.status === "pending" ||
                            selectedOrder.status === "submitted"
                          ? "#d97706"
                          : selectedOrder.status === "rejected" ||
                              selectedOrder.status === "cancelled"
                            ? "#dc2626"
                            : "#2563eb",
                  }}
                >
                  {selectedOrder.status.charAt(0).toUpperCase() +
                    selectedOrder.status.slice(1)}
                </span>
              </div>

              <div style={{ padding: "0.75rem 1rem" }}>
                <DetailRow
                  label="Order ID"
                  value={selectedOrder.order_request_id}
                />
                <DetailRow label="Symbol" value={selectedOrder.symbol} />
                <DetailRow
                  label="Side"
                  value={selectedOrder.side.toUpperCase()}
                  valueColor={
                    selectedOrder.side.toLowerCase() === "buy"
                      ? "#16a34a"
                      : "#dc2626"
                  }
                />
                <DetailRow label="Type" value={selectedOrder.order_type} />
                <DetailRow
                  label="Quantity"
                  value={String(selectedOrder.qty)}
                />
                <DetailRow
                  label="Strategy"
                  value={selectedOrder.strategy_code}
                />
                <DetailRow label="Created" value={selectedOrder.created_at} />
              </div>
            </div>

            {/* State Events (template timeline pattern) */}
            <div className="card-panel">
              <div className="card-panel-header">
                <span className="card-panel-title">State Events</span>
              </div>
              <div style={{ padding: "0.75rem 1rem" }}>
                {[
                  { label: "Order Created", color: "#3b82f6" },
                  { label: "Sent to Broker", color: "#8b5cf6" },
                  ...(selectedOrder.status !== "cancelled" &&
                  selectedOrder.status !== "rejected"
                    ? [{ label: "Acknowledged", color: "#10b981" }]
                    : []),
                  ...(selectedOrder.status === "filled" ||
                  selectedOrder.status === "partial"
                    ? [{ label: "Fill Received", color: "#10b981" }]
                    : []),
                  ...(selectedOrder.status === "cancelled"
                    ? [{ label: "Cancelled", color: "#ef4444" }]
                    : []),
                  ...(selectedOrder.status === "rejected"
                    ? [{ label: "Rejected", color: "#ef4444" }]
                    : []),
                ].map((ev, i, arr) => (
                  <div key={i} className="event-timeline-item">
                    <div className="event-timeline-line">
                      <span
                        className="event-timeline-dot"
                        style={{ backgroundColor: ev.color }}
                      />
                      {i < arr.length - 1 && (
                        <span
                          className="event-timeline-connector"
                          style={{ backgroundColor: "var(--border-color)" }}
                        />
                      )}
                    </div>
                    <div className="event-timeline-content">
                      <p
                        className="event-timeline-label"
                        style={{ color: ev.color }}
                      >
                        {ev.label}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* View Full Detail link */}
            <div className="card-panel">
              <button
                onClick={() =>
                  navigate(`/orders/${selectedOrder.order_request_id}`)
                }
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "0.35rem",
                  width: "100%",
                  padding: "0.6rem",
                  background: "transparent",
                  border: "1px solid var(--border-color)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--accent-color)",
                  fontSize: "var(--text-xs)",
                  fontWeight: 600,
                  cursor: "pointer",
                  transition: "background-color 0.12s ease",
                }}
              >
                <ExternalLink size={12} />
                <span>View Full Detail</span>
                <ChevronRight size={12} />
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
