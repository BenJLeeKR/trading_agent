import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { OrderDetail as OrderDetailType, OrderEvent, BrokerOrderView } from "../types/api";
import { getOrderDetail, getOrderEvents, getBrokerOrders } from "../api/client";
import { DataTable } from "./common/DataTable";
import { Panel } from "./common/Panel";
import { DetailField } from "./common/DetailField";
import { SectionDivider } from "./common/SectionDivider";
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
      <p className="back-link">
        <Link to="/orders">&larr; Back to Orders</Link>
      </p>

      {/* ── Summary Panel ── */}
      <Panel
        title="Order Detail"
        subtitle={`${order.symbol} · ${order.side} · ${order.order_type}`}
        headerRight={
          <code className="order-id">
            {order.order_request_id}
          </code>
        }
      >
        <div className="detail-grid">
          <DetailField label="Symbol" value={order.symbol} />
          <DetailField label="Side" value={order.side} />
          <DetailField
            label="Status"
            value={<StatusBadge status={order.status} />}
          />
          <DetailField label="Order Type" value={order.order_type} />
          <DetailField label="Qty" value={order.qty} />
          <DetailField
            label="Filled Qty"
            value={order.filled_qty ?? "\u2014"}
          />
          <DetailField
            label="Avg Fill Price"
            value={order.avg_fill_price ?? "\u2014"}
            mono
          />
          <DetailField label="Strategy" value={order.strategy_code} />
          <DetailField label="Created" value={order.created_at} />
          <DetailField
            label="Updated"
            value={order.updated_at ?? "\u2014"}
          />
        </div>

        {order.error_message && (
          <div className="text-error error-block">
            <strong>Error:</strong> {order.error_message}
          </div>
        )}

        {(order.decision_context_id || order.trade_decision_id) && (
          <>
            <SectionDivider label="Decision Links:" />
            <div className="decision-links">
              {order.decision_context_id && (
                <span>
                  Context:{" "}
                  <Link to={`/decisions?contextId=${order.decision_context_id}`}>
                    <code>{order.decision_context_id}</code>
                  </Link>
                </span>
              )}
              {order.trade_decision_id && (
                <span>
                  Decision:{" "}
                  <Link
                    to={`/decisions?contextId=${order.decision_context_id ?? order.trade_decision_id}`}
                  >
                    <code>{order.trade_decision_id}</code>
                  </Link>
                </span>
              )}
            </div>
          </>
        )}
      </Panel>

      {/* ── State Events Panel ── */}
      <Panel
        title={`State Events (${events.length})`}
      >
        <DataTable
          columns={eventColumns}
          data={events}
          keyField="event_id"
          emptyMessage="No state events recorded."
          compact
        />
      </Panel>

      {/* ── Broker Orders Panel ── */}
      <Panel
        title={`Broker Orders (${brokerOrders.length})`}
      >
        <DataTable
          columns={brokerColumns}
          data={brokerOrders}
          keyField="broker_order_id"
          emptyMessage="No broker orders."
          compact
        />
      </Panel>
    </section>
  );
}
