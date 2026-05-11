import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { OrderDetail as OrderDetailType, OrderEvent, BrokerOrderView } from "../types/api";
import { getOrderDetail, getOrderEvents, getBrokerOrders } from "../api/client";
import { useEnumMetadata, getEnumLabel } from "../hooks/useEnumMetadata";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { ErrorBanner } from "./common/ErrorBanner";
import type { Column } from "./common/DataTable";
import { ArrowLeft } from "lucide-react";

export default function OrderDetail() {
  const { orderId } = useParams<{ orderId: string }>();
  const { fieldMap } = useEnumMetadata();
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
        const msg = err instanceof Error ? err.message : "주문 상세를 불러오지 못했습니다";
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, [orderId]);

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;
  if (!order) return <p className="p-6 text-[#64748b]">주문을 찾을 수 없습니다.</p>;

  const eventColumns: Column<OrderEvent>[] = [
    { key: "timestamp", header: "시각" },
    {
      key: "from_status",
      header: "이전",
      render: (r) => (
        <StatusBadge status={r.from_status}>
          {getEnumLabel(fieldMap, "order_status", r.from_status)}
        </StatusBadge>
      ),
    },
    {
      key: "to_status",
      header: "이후",
      render: (r) => (
        <StatusBadge status={r.to_status}>
          {getEnumLabel(fieldMap, "order_status", r.to_status)}
        </StatusBadge>
      ),
    },
    { key: "reason", header: "사유" },
  ];

  const brokerColumns: Column<BrokerOrderView>[] = [
    { key: "broker_id", header: "브로커" },
    { key: "native_order_id", header: "Native 주문 ID" },
    {
      key: "status",
      header: "상태",
      render: (r) => (
        <StatusBadge status={r.status}>
          {getEnumLabel(fieldMap, "order_status", r.status)}
        </StatusBadge>
      ),
    },
    { key: "submitted_at", header: "제출 시각" },
  ];

  return (
    <div className="p-6 space-y-6">
      {/* Back link */}
      <Link
        to="/orders"
        className="inline-flex items-center gap-1 text-sm text-[#64748b] hover:text-[#0f172a] transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        주문 목록으로
      </Link>

      {/* Order Detail card */}
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-[#0f172a]">주문 상세</h3>
            <p className="text-sm text-[#64748b]">
              {order.symbol} · {getEnumLabel(fieldMap, "side", order.side)} ·{" "}
              <span title={order.order_type ?? ""}>
                {getEnumLabel(fieldMap, "order_type", order.order_type)}
              </span>
            </p>
          </div>
          <code className="text-xs font-mono text-[#64748b] bg-[#f8fafc] px-2 py-1 rounded">
            {order.order_request_id}
          </code>
        </div>

        <dl className="grid grid-cols-2 gap-4">
          <div>
            <dt className="text-sm text-[#64748b]">심볼</dt>
            <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{order.symbol}</dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">매매</dt>
            <dd className="mt-0.5">
              <StatusBadge variant={order.side.toLowerCase() === "buy" ? "success" : "error"}>
                {getEnumLabel(fieldMap, "side", order.side)}
              </StatusBadge>
            </dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">상태</dt>
            <dd className="mt-0.5">
              <StatusBadge status={order.status}>
                {getEnumLabel(fieldMap, "order_status", order.status)}
              </StatusBadge>
            </dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">주문 유형</dt>
            <dd className="text-sm font-medium text-[#0f172a] mt-0.5">
              {getEnumLabel(fieldMap, "order_type", order.order_type)}
              <span className="ml-2 text-xs text-[#94a3b8] font-mono">
                ({order.order_type})
              </span>
            </dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">수량</dt>
            <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{order.requested_quantity}</dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">체결 수량</dt>
            <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{order.filled_qty ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">평균 체결가</dt>
            <dd className="text-sm font-mono text-[#0f172a] mt-0.5">{order.avg_fill_price ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">클라이언트 주문 ID</dt>
            <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{order.client_order_id}</dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">생성일</dt>
            <dd className="text-sm text-[#0f172a] mt-0.5">{order.created_at ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-sm text-[#64748b]">수정일</dt>
            <dd className="text-sm text-[#0f172a] mt-0.5">{order.updated_at ?? "—"}</dd>
          </div>
        </dl>

        {order.error_message && (
          <div className="mt-4 p-3 bg-[#fef2f2] border border-[#f87171] rounded-lg">
            <strong className="text-sm text-[#dc2626]">오류:</strong>
            <span className="text-sm text-[#dc2626] ml-1">{order.error_message}</span>
          </div>
        )}

        {(order.decision_context_id || order.trade_decision_id) && (
          <div className="mt-4 pt-4 border-t border-[#e2e8f0]">
            <p className="text-xs font-semibold text-[#64748b] mb-2">의사결정 연결</p>
            <div className="flex gap-4">
              {order.decision_context_id && (
                <span className="text-sm">
                  컨텍스트:{" "}
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
                  의사결정:{" "}
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
        <h4 className="text-sm font-medium text-[#0f172a]">상태 이벤트 ({events.length})</h4>
        <DataTable
          columns={eventColumns}
          data={events}
          idKey="event_id"
          emptyMessage="기록된 상태 이벤트가 없습니다."
          compact
        />
      </div>

      {/* Broker Orders */}
      <div className="space-y-2">
        <h4 className="text-sm font-medium text-[#0f172a]">브로커 주문 ({brokerOrders.length})</h4>
        <DataTable
          columns={brokerColumns}
          data={brokerOrders}
          idKey="broker_order_id"
          emptyMessage="브로커 주문이 없습니다."
          compact
        />
      </div>
    </div>
  );
}
