import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { OrderDetail as OrderDetailType, OrderEvent, BrokerOrderView } from "../types/api";
import { getOrderDetail, getOrderEvents, getBrokerOrders } from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { ErrorBanner } from "./common/ErrorBanner";
import type { Column } from "./common/DataTable";
import { ArrowLeft } from "lucide-react";

export default function OrderDetail() {
  const { orderId } = useParams<{ orderId: string }>();
  const [order, setOrder] = useState<OrderDetailType | null>(null);
  const [events, setEvents] = useState<OrderEvent[]>([]);
  const [brokerOrders, setBrokerOrders] = useState<BrokerOrderView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!orderId) return;
    setLoading(true);
    setError(null);
    Promise.all([
      getOrderDetail(orderId),
      getOrderEvents(orderId),
      getBrokerOrders(orderId),
    ])
      .then(([o, e, b]) => {
        setOrder(o);
        setEvents(e);
        setBrokerOrders(b);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Failed to load order detail";
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, [orderId]);

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;
  if (!order) return <p className="p-6 text-[#64748b]">Order not found.</p>;

  const eventColumns: Column<OrderEvent>[] = [
    { key: "timestamp", header: "Timestamp" },
    {
      key: "from_status",
      header: "From",
      render: (r) => <StatusBadge status={r.from_status} />,
    },
    {
      key: "to_status",
      header: "To",
      render: (r) => <StatusBadge status={r.to_status} />,
    },
    { key: "reason", header: "Reason" },
  ];

  const brokerColumns: Column<BrokerOrderView>[] = [
    { key: "broker_id", header: "Broker" },
    { key: "native_order_id", header: "Native Order ID" },
    {
      key: "status",
      header: "Status",
      render: (r) => <StatusBadge status={r.status} />,
    },
    { key: "submitted_at", header: "Submitted At" },
  ];

  return (
    <div className="p-6 space-y-6">
      {/* Back link */}
      <Link
        to="/orders"
        className="inline-flex items-center gap-1 text-sm text-[#64748b] hover:text-[#0f172a] transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Orders
      </Link>

      {/* Order Detail card */}
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-[#0f172a]">Order Detail</h3>
            <p className="text-sm text-[#64748b]">{order.symbol} · {order.side} · {order.order_type}</p>
          </div>
          <code className="text-xs font-mono text-[#64748b] bg-[#f8fafc] px-2 py-1 rounded">
            {order.order_request_id}
          </code>
        </div>

        <dl className="grid grid-cols-2 gap-4">
          <div>
            <dt className="text-sm text-[#64748b]">Symbol</dt>
            <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{order.symbol}</dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">Side</dt>
            <dd className="mt-0.5">
              <StatusBadge variant={order.side.toLowerCase() === "buy" ? "success" : "error"}>
                {order.side}
              </StatusBadge>
            </dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">Status</dt>
            <dd className="mt-0.5"><StatusBadge status={order.status} /></dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">Order Type</dt>
            <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{order.order_type}</dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">Qty</dt>
            <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{order.requested_quantity}</dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">Filled Qty</dt>
            <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{order.filled_qty ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">Avg Fill Price</dt>
            <dd className="text-sm font-mono text-[#0f172a] mt-0.5">{order.avg_fill_price ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">Client Order ID</dt>
            <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{order.client_order_id}</dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">Created</dt>
            <dd className="text-sm text-[#0f172a] mt-0.5">{order.created_at ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">Updated</dt>
            <dd className="text-sm text-[#0f172a] mt-0.5">{order.updated_at ?? "—"}</dd>
          </div>
        </dl>

        {order.error_message && (
          <div className="mt-4 p-3 bg-[#fef2f2] border border-[#f87171] rounded-lg">
            <strong className="text-sm text-[#dc2626]">Error:</strong>
            <span className="text-sm text-[#dc2626] ml-1">{order.error_message}</span>
          </div>
        )}

        {(order.decision_context_id || order.trade_decision_id) && (
          <div className="mt-4 pt-4 border-t border-[#e2e8f0]">
            <p className="text-xs font-semibold text-[#64748b] mb-2">Decision Links</p>
            <div className="flex gap-4">
              {order.decision_context_id && (
                <span className="text-sm">
                  Context:{" "}
                  <Link
                    to={`/decisions?contextId=${order.decision_context_id}`}
                    className="text-[#3b82f6] hover:text-[#2563eb] font-mono text-xs"
                  >
                    {order.decision_context_id}
                  </Link>
                </span>
              )}
              {order.trade_decision_id && (
                <span className="text-sm">
                  Decision:{" "}
                  <Link
                    to={`/decisions?contextId=${order.decision_context_id ?? order.trade_decision_id}`}
                    className="text-[#3b82f6] hover:text-[#2563eb] font-mono text-xs"
                  >
                    {order.trade_decision_id}
                  </Link>
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* State Events */}
      <div className="space-y-2">
        <h4 className="text-sm font-medium text-[#0f172a]">State Events ({events.length})</h4>
        <DataTable
          columns={eventColumns}
          data={events}
          idKey="event_id"
          emptyMessage="No state events recorded."
          compact
        />
      </div>

      {/* Broker Orders */}
      <div className="space-y-2">
        <h4 className="text-sm font-medium text-[#0f172a]">Broker Orders ({brokerOrders.length})</h4>
        <DataTable
          columns={brokerColumns}
          data={brokerOrders}
          idKey="broker_order_id"
          emptyMessage="No broker orders."
          compact
        />
      </div>
    </div>
  );
}
