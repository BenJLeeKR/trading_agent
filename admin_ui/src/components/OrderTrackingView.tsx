import { useState, useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import { FilterBar } from "./common/FilterBar";
import { DataTable, type Column } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { ErrorBanner } from "./common/ErrorBanner";
import { X, RefreshCw, ExternalLink } from "lucide-react";
import {
  getOrders,
  getOrderDetail,
  getOrderEvents,
  getBrokerOrders,
} from "../api/client";
import type {
  OrderSummary,
  OrderDetail,
  OrderEvent,
  BrokerOrderView,
} from "../types/api";

/* ── Helpers ── */
function sideLabel(side: string): string {
  switch (side) {
    case "buy": return "매수";
    case "sell": return "매도";
    default: return side;
  }
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    submitted: "제출됨",
    acknowledged: "접수됨",
    partially_filled: "부분체결",
    filled: "체결",
    rejected: "거부됨",
    cancelled: "취소됨",
    pending: "대기",
    reconcile_required: "조정필요",
  };
  return map[status] ?? status;
}

function statusVariant(status: string): "success" | "warning" | "error" | "info" | "neutral" {
  switch (status) {
    case "filled": return "success";
    case "partially_filled": return "warning";
    case "acknowledged":
    case "submitted":
    case "pending": return "info";
    case "rejected":
    case "cancelled": return "error";
    case "reconcile_required": return "warning";
    default: return "neutral";
  }
}

function formatTime(dateStr: string | null): string {
  if (!dateStr) return "-";
  try {
    return new Date(dateStr).toLocaleString("ko-KR", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return dateStr;
  }
}

function formatPrice(val: string | number | null | undefined): string {
  if (val == null) return "-";
  const num = typeof val === "string" ? parseFloat(val) : val;
  if (isNaN(num)) return "-";
  return `$${num.toFixed(2)}`;
}

/* ── Columns ── */
const orderColumns: Column<OrderSummary>[] = [
  { key: "order_request_id", header: "주문 ID", width: "150px" },
  {
    key: "symbol",
    header: "종목",
    render: (row: OrderSummary) => (
      <span className="font-semibold text-[#0f172a]">{row.symbol ?? "-"}</span>
    ),
  },
  {
    key: "side",
    header: "구분",
    render: (row: OrderSummary) => (
      <StatusBadge variant={row.side === "buy" ? "success" : "error"}>
        {sideLabel(row.side)}
      </StatusBadge>
    ),
  },
  {
    key: "requested_quantity",
    header: "수량",
    render: (row: OrderSummary) => `${row.requested_quantity}주`,
  },
  {
    key: "status",
    header: "상태",
    render: (row: OrderSummary) => (
      <StatusBadge variant={statusVariant(row.status)}>
        {statusLabel(row.status)}
      </StatusBadge>
    ),
  },
  { key: "created_at", header: "생성 시간", width: "150px", render: (row: OrderSummary) => formatTime(row.created_at) },
];

const eventColumns: Column<OrderEvent>[] = [
  { key: "from_status", header: "이전 상태", width: "100px", render: (row: OrderEvent) => statusLabel(row.from_status) },
  { key: "to_status", header: "이후 상태", width: "100px", render: (row: OrderEvent) => statusLabel(row.to_status) },
  { key: "timestamp", header: "시간", width: "150px", render: (row: OrderEvent) => formatTime(row.timestamp) },
  { key: "reason", header: "사유" },
];

const brokerColumns: Column<BrokerOrderView>[] = [
  { key: "broker_name", header: "브로커", width: "100px" },
  { key: "broker_native_order_id", header: "ODNO", width: "120px" },
  {
    key: "broker_status",
    header: "상태",
    render: (row: BrokerOrderView) => (
      <StatusBadge variant={statusVariant(row.broker_status)}>
        {statusLabel(row.broker_status)}
      </StatusBadge>
    ),
  },
  { key: "last_synced_at", header: "마지막 동기화", width: "150px", render: (row: BrokerOrderView) => formatTime(row.last_synced_at) },
];

/* ── Component ── */
export default function OrderTrackingView() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sideFilter, setSideFilter] = useState("");
  const [selectedOrder, setSelectedOrder] = useState<OrderSummary | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [orders, setOrders] = useState<OrderSummary[]>([]);

  // Detail state
  const [detailLoading, setDetailLoading] = useState(false);
  const [orderDetail, setOrderDetail] = useState<OrderDetail | null>(null);
  const [orderEvents, setOrderEvents] = useState<OrderEvent[]>([]);
  const [brokerOrders, setBrokerOrders] = useState<BrokerOrderView[]>([]);

  /* ── Fetch orders list ── */
  const fetchOrders = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getOrders();
      setOrders(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "주문 데이터 로딩 실패";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOrders();
  }, []);

  /* ── Fetch detail on selection ── */
  useEffect(() => {
    if (!selectedOrder?.order_request_id) {
      setOrderDetail(null);
      setOrderEvents([]);
      setBrokerOrders([]);
      return;
    }

    setDetailLoading(true);
    const id = selectedOrder.order_request_id;

    Promise.all([
      getOrderDetail(id).then(setOrderDetail).catch(() => setOrderDetail(null)),
      getOrderEvents(id).then(setOrderEvents).catch(() => setOrderEvents([])),
      getBrokerOrders(id).then(setBrokerOrders).catch(() => setBrokerOrders([])),
    ]).finally(() => setDetailLoading(false));
  }, [selectedOrder?.order_request_id]);

  /* ── Filtering ── */
  const filteredOrders = useMemo(() => {
    return orders.filter((order) => {
      const matchesSearch =
        (order.symbol ?? "").toLowerCase().includes(search.toLowerCase()) ||
        order.order_request_id.toLowerCase().includes(search.toLowerCase());
      const matchesStatus = !statusFilter || order.status === statusFilter;
      const matchesSide = !sideFilter || order.side === sideFilter;
      return matchesSearch && matchesStatus && matchesSide;
    });
  }, [orders, search, statusFilter, sideFilter]);

  /* ── Loading / Error ── */
  if (loading) return <LoadingSpinner text="주문 데이터 로딩 중..." />;

  if (error) {
    return (
      <div className="p-6 space-y-4">
        <ErrorBanner message={error} onDismiss={() => setError(null)} />
        <button
          onClick={fetchOrders}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-[#3b82f6] rounded-lg hover:bg-[#2563eb] transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
          다시 시도
        </button>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">주문 추적</h1>
        <p className="text-sm text-[#64748b] mt-1">AI 판단에서 실제 주문 제출까지 추적</p>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Orders List */}
        <div className={selectedOrder ? "col-span-7" : "col-span-12"}>
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-4 mb-4">
            <FilterBar
              searchPlaceholder="종목 또는 주문 ID 검색..."
              searchValue={search}
              onSearchChange={setSearch}
              filters={[
                {
                  key: "status",
                  label: "상태",
                  options: [
                    { label: "전체", value: "" },
                    { label: "제출됨", value: "submitted" },
                    { label: "접수됨", value: "acknowledged" },
                    { label: "부분체결", value: "partially_filled" },
                    { label: "체결", value: "filled" },
                    { label: "거부됨", value: "rejected" },
                    { label: "취소됨", value: "cancelled" },
                    { label: "조정필요", value: "reconcile_required" },
                  ],
                  value: statusFilter,
                  onChange: setStatusFilter,
                },
                {
                  key: "side",
                  label: "구분",
                  options: [
                    { label: "전체", value: "" },
                    { label: "매수", value: "buy" },
                    { label: "매도", value: "sell" },
                  ],
                  value: sideFilter,
                  onChange: setSideFilter,
                },
              ]}
              onClearAll={() => {
                setSearch("");
                setStatusFilter("");
                setSideFilter("");
              }}
            />
          </div>
          {filteredOrders.length > 0 ? (
            <DataTable
              columns={orderColumns}
              data={filteredOrders}
              onRowClick={setSelectedOrder}
              selectedId={selectedOrder?.order_request_id}
              idKey="order_request_id"
            />
          ) : (
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
              <p className="text-sm text-[#94a3b8]">검색 결과가 없습니다</p>
            </div>
          )}
        </div>

        {/* Order Detail Panel */}
        {selectedOrder && (
          <div className="col-span-5 space-y-4">
            {detailLoading ? (
              <LoadingSpinner text="주문 상세 로딩 중..." />
            ) : (
              <>
                {/* Order Info Card */}
                <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold text-[#0f172a]">주문 상세</h3>
                    <button
                      onClick={() => setSelectedOrder(null)}
                      className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                  <dl className="grid grid-cols-2 gap-4">
                    <div>
                      <dt className="text-sm text-[#64748b]">주문 ID</dt>
                      <dd className="text-sm font-mono font-medium text-[#0f172a] mt-0.5">
                        {selectedOrder.order_request_id}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-sm text-[#64748b]">종목</dt>
                      <dd className="text-sm font-semibold text-[#0f172a] mt-0.5">
                        {selectedOrder.symbol ?? "-"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-sm text-[#64748b]">구분</dt>
                      <dd className="mt-0.5">
                        <StatusBadge variant={selectedOrder.side === "buy" ? "success" : "error"}>
                          {sideLabel(selectedOrder.side)}
                        </StatusBadge>
                      </dd>
                    </div>
                    <div>
                      <dt className="text-sm text-[#64748b]">상태</dt>
                      <dd className="mt-0.5">
                        <StatusBadge variant={statusVariant(selectedOrder.status)}>
                          {statusLabel(selectedOrder.status)}
                        </StatusBadge>
                      </dd>
                    </div>
                    <div>
                      <dt className="text-sm text-[#64748b]">수량</dt>
                      <dd className="text-sm font-medium text-[#0f172a] mt-0.5">
                        {selectedOrder.requested_quantity}주
                      </dd>
                    </div>
                    <div>
                      <dt className="text-sm text-[#64748b]">가격</dt>
                      <dd className="text-sm font-medium text-[#0f172a] mt-0.5">
                        {formatPrice(selectedOrder.requested_price)}
                      </dd>
                    </div>
                    {orderDetail && (
                      <>
                        <div>
                          <dt className="text-sm text-[#64748b]">체결 수량</dt>
                          <dd className="text-sm font-medium text-[#0f172a] mt-0.5">
                            {orderDetail.filled_qty ?? "-"}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-sm text-[#64748b]">평균 체결가</dt>
                          <dd className="text-sm font-medium text-[#0f172a] mt-0.5">
                            {formatPrice(orderDetail.avg_fill_price)}
                          </dd>
                        </div>
                        {orderDetail.error_message && (
                          <div className="col-span-2">
                            <dt className="text-sm text-[#64748b]">오류 메시지</dt>
                            <dd className="text-sm text-[#dc2626] mt-0.5">{orderDetail.error_message}</dd>
                          </div>
                        )}
                      </>
                    )}
                  </dl>
                </div>

                {/* State Timeline */}
                <div className="space-y-2">
                  <h4 className="text-sm font-medium text-[#0f172a]">상태 전이 타임라인</h4>
                  {orderEvents.length > 0 ? (
                    <DataTable columns={eventColumns} data={orderEvents} idKey="event_id" compact />
                  ) : (
                    <div className="bg-white rounded-xl border border-[#e2e8f0] p-4 text-center">
                      <p className="text-xs text-[#94a3b8]">상태 전이 이력이 없습니다</p>
                    </div>
                  )}
                </div>

                {/* Broker Orders */}
                <div className="space-y-2">
                  <h4 className="text-sm font-medium text-[#0f172a]">브로커 주문</h4>
                  {brokerOrders.length > 0 ? (
                    <DataTable columns={brokerColumns} data={brokerOrders} idKey="broker_order_id" compact />
                  ) : (
                    <div className="bg-white rounded-xl border border-[#e2e8f0] p-4 text-center">
                      <p className="text-xs text-[#94a3b8]">브로커 주문 내역이 없습니다</p>
                    </div>
                  )}
                </div>

                {/* Submission Path Summary */}
                <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
                  <h4 className="text-sm font-medium text-[#0f172a] mb-4">제출 경로 요약</h4>
                  <div className="space-y-3">
                    <div className="flex items-center justify-between py-2 border-b border-[#f1f5f9]">
                      <span className="text-sm text-[#64748b]">Trade Decision</span>
                      <span className="text-sm font-mono font-medium text-[#3b82f6]">
                        {selectedOrder.trade_decision_id ?? "-"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between py-2 border-b border-[#f1f5f9]">
                      <span className="text-sm text-[#64748b]">Correlation ID</span>
                      <span className="text-sm font-mono font-medium text-[#3b82f6]">
                        {selectedOrder.correlation_id ?? "-"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between py-2">
                      <span className="text-sm text-[#64748b]">계좌 ID</span>
                      <span className="text-sm font-mono font-medium text-[#3b82f6]">
                        {selectedOrder.account_id}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Link to existing /orders/:id */}
                <div className="flex justify-end">
                  <Link
                    to={`/orders/${selectedOrder.order_request_id}`}
                    className="flex items-center gap-1.5 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
                  >
                    <ExternalLink className="h-4 w-4" />
                    기존 주문 상세 화면에서 보기
                  </Link>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
