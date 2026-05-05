import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { OrderDetail as OrderDetailType, OrderEvent, BrokerOrderView } from "../types/api";
import { getOrderDetail, getOrderEvents, getBrokerOrders } from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { ErrorBanner } from "./common/ErrorBanner";
import type { Column } from "./common/DataTable";

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
  if (!order) return <p>Order not found.</p>;

  const eventColumns: Column<OrderEvent>[] = [
    { key: "timestamp", label: "Timestamp" },
    {
      key: "from_status",
      label: "From",
      render: (r) => <StatusBadge status={r.from_status} />,
    },
    {
      key: "to_status",
      label: "To",
      render: (r) => <StatusBadge status={r.to_status} />,
    },
    { key: "reason", label: "Reason" },
  ];

  const brokerColumns: Column<BrokerOrderView>[] = [
    { key: "broker_id", label: "Broker" },
    { key: "native_order_id", label: "Native Order ID" },
    {
      key: "status",
      label: "Status",
      render: (r) => <StatusBadge status={r.status} />,
    },
    { key: "submitted_at", label: "Submitted At" },
  ];

  return (
    <section>
      <p>
        <Link to="/orders">&larr; Back to Orders</Link>
      </p>

      <div className="page-header">
        <h2>Order Detail</h2>
        <p>ID: <code>{order.order_request_id}</code></p>
      </div>

      <article>
        <header><strong>Summary</strong></header>
        <div className="data-grid-auto">
          <div><strong>Symbol:</strong> {order.symbol}</div>
          <div><strong>Side:</strong> {order.side}</div>
          <div>
            <strong>Status:</strong> <StatusBadge status={order.status} />
          </div>
          <div><strong>Order Type:</strong> {order.order_type}</div>
          <div><strong>Qty:</strong> {order.qty}</div>
          <div><strong>Filled Qty:</strong> {order.filled_qty ?? "—"}</div>
          <div><strong>Avg Fill Price:</strong> {order.avg_fill_price ?? "—"}</div>
          <div><strong>Strategy:</strong> {order.strategy_code}</div>
          <div><strong>Created:</strong> {order.created_at}</div>
          <div><strong>Updated:</strong> {order.updated_at ?? "—"}</div>
          {order.error_message && (
            <div className="text-error">
              <strong>Error:</strong> {order.error_message}
            </div>
          )}
        </div>
        {(order.decision_context_id || order.trade_decision_id) && (
          <footer>
            <strong>Decision Links:</strong>
            {order.decision_context_id && (
              <span style={{ marginLeft: "0.5rem" }}>
                Context:{" "}
                <Link to={`/decisions?contextId=${order.decision_context_id}`}>
                  <code>{order.decision_context_id}</code>
                </Link>
              </span>
            )}
            {order.trade_decision_id && (
              <span style={{ marginLeft: "1rem" }}>
                Decision:{" "}
                <Link to={`/decisions?contextId=${order.decision_context_id ?? order.trade_decision_id}`}>
                  <code>{order.trade_decision_id}</code>
                </Link>
              </span>
            )}
          </footer>
        )}
      </article>

      <article>
        <header><strong>State Events ({events.length})</strong></header>
        <DataTable
          columns={eventColumns}
          data={events}
          keyField="event_id"
          emptyMessage="No state events recorded."
        />
      </article>

      <article>
        <header><strong>Broker Orders ({brokerOrders.length})</strong></header>
        <DataTable
          columns={brokerColumns}
          data={brokerOrders}
          keyField="broker_order_id"
          emptyMessage="No broker orders."
        />
      </article>
    </section>
  );
}
