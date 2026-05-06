import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { OrderSummary } from "../types/api";
import { getOrders } from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { FilterBar } from "./common/FilterBar";
import { X } from "lucide-react";

export default function OrdersView() {
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sideFilter, setSideFilter] = useState("");
  const [selectedOrder, setSelectedOrder] = useState<OrderSummary | null>(null);
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
      if (searchText && !(o.symbol ?? "").toLowerCase().includes(searchText.toLowerCase()) && !o.order_request_id.toLowerCase().includes(searchText.toLowerCase())) {
        return false;
      }
      if (statusFilter && o.status !== statusFilter) return false;
      if (sideFilter && o.side !== sideFilter) return false;
      return true;
    });
  }, [orders, searchText, statusFilter, sideFilter]);

  const orderColumns = [
    { key: "order_request_id", header: "Order ID", width: "100px", render: (r: OrderSummary) => (
      <code className="text-xs">{r.order_request_id.slice(0, 8)}…</code>
    )},
    { key: "symbol", header: "Symbol" },
    { key: "side", header: "Side", render: (r: OrderSummary) => (
      <StatusBadge variant={r.side.toLowerCase() === "buy" ? "success" : "error"}>{r.side.toUpperCase()}</StatusBadge>
    )},
    { key: "requested_quantity", header: "Qty" },
    { key: "status", header: "Status", render: (r: OrderSummary) => {
      const variants: Record<string, "success" | "warning" | "error" | "info" | "neutral"> = {
        filled: "success",
        pending: "warning",
        rejected: "error",
        partial: "info",
        submitted: "info",
        cancelled: "neutral",
      };
      return <StatusBadge variant={variants[r.status] || "info"}>{r.status.toUpperCase()}</StatusBadge>;
    }},
    { key: "created_at", header: "Created" },
  ];

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">Orders</h1>
        <p className="text-sm text-[#64748b] mt-1">View order lifecycle, broker mapping, and decision lineage</p>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Orders List */}
        <div className={selectedOrder ? "col-span-7" : "col-span-12"}>
          <FilterBar
            searchPlaceholder="Search symbol or order ID..."
            searchValue={searchText}
            onSearchChange={setSearchText}
            filters={[
              {
                key: "status",
                label: "Status",
                options: [
                  { label: "Filled", value: "filled" },
                  { label: "Pending", value: "pending" },
                  { label: "Rejected", value: "rejected" },
                  { label: "Partial", value: "partial" },
                  { label: "Submitted", value: "submitted" },
                  { label: "Cancelled", value: "cancelled" },
                ],
                value: statusFilter,
                onChange: setStatusFilter,
              },
              {
                key: "side",
                label: "Side",
                options: [
                  { label: "Buy", value: "buy" },
                  { label: "Sell", value: "sell" },
                ],
                value: sideFilter,
                onChange: setSideFilter,
              },
            ]}
            onClearAll={() => {
              setSearchText("");
              setStatusFilter("");
              setSideFilter("");
            }}
          />
          <DataTable
            columns={orderColumns}
            data={filteredOrders}
            idKey="order_request_id"
            onRowClick={(row) => {
              if (selectedOrder?.order_request_id === row.order_request_id) {
                setSelectedOrder(null);
              } else {
                setSelectedOrder(row);
              }
            }}
            selectedId={selectedOrder?.order_request_id}
            emptyMessage="No orders found."
          />
        </div>

        {/* Order Detail Panel */}
        {selectedOrder && (
          <div className="col-span-5 space-y-4">
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-[#0f172a]">Order Detail</h3>
                <button
                  onClick={() => setSelectedOrder(null)}
                  className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <dl className="space-y-3">
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Order ID</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedOrder.order_request_id}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Symbol</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedOrder.symbol ?? "—"}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Side</dt>
                  <dd><StatusBadge variant={selectedOrder.side.toLowerCase() === "buy" ? "success" : "error"}>{selectedOrder.side.toUpperCase()}</StatusBadge></dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Quantity</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedOrder.requested_quantity}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Status</dt>
                  <dd><StatusBadge status={selectedOrder.status} /></dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Client Order ID</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedOrder.client_order_id}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Created</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedOrder.created_at ?? "—"}</dd>
                </div>
              </dl>
              <div className="mt-4 pt-4 border-t border-[#e2e8f0]">
                <button
                  onClick={() => navigate(`/orders/${selectedOrder.order_request_id}`)}
                  className="w-full text-center text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
                >
                  View full details →
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
