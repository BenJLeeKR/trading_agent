import { useEffect, useMemo, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import type { OrderSummary } from "../types/api";
import { getOrders } from "../api/client";
import { DataTable, type Column } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { FilterBar } from "./common/FilterBar";
import { useEnumMetadata, getEnumLabel } from "../hooks/useEnumMetadata";
import { X } from "lucide-react";
import { formatKstDateTime } from "../lib/utils";

function formatNumber(value: number | string | null | undefined) {
  if (value == null) return "—";
  const numeric = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(numeric)) return "—";
  return new Intl.NumberFormat("ko-KR").format(numeric);
}

function todayKst(): string {
  const formatter = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return formatter.format(new Date());
}

function formatIsoToKstDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  const formatter = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return formatter.format(parsed);
}

export default function OrdersView() {
  const { fieldMap } = useEnumMetadata();
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sideFilter, setSideFilter] = useState("");
  const [selectedDate, setSelectedDate] = useState(todayKst());
  const [selectedOrder, setSelectedOrder] = useState<OrderSummary | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const navigate = useNavigate();

  const location = useLocation();

  // ── Read initial symbol from URL query params ───────────────────
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const symbolParam = params.get("symbol");
    if (symbolParam) {
      setSearchText(symbolParam);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getOrders(undefined, 10000)
      .then(setOrders)
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "주문을 불러오지 못했습니다";
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, []);

  const filteredOrders = useMemo(() => {
    return orders.filter((o) => {
      if (selectedDate) {
        const orderDate = formatIsoToKstDate(o.created_at);
        if (orderDate !== selectedDate) {
          return false;
        }
      }
      if (searchText && !(o.symbol ?? "").toLowerCase().includes(searchText.toLowerCase()) && !o.order_request_id.toLowerCase().includes(searchText.toLowerCase())) {
        return false;
      }
      if (statusFilter && o.status !== statusFilter) return false;
      if (sideFilter && o.side !== sideFilter) return false;
      return true;
    });
  }, [orders, selectedDate, searchText, statusFilter, sideFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredOrders.length / pageSize));
  const safePage = Math.min(currentPage, totalPages);
  const pagedOrders = useMemo(() => {
    return filteredOrders.slice((safePage - 1) * pageSize, safePage * pageSize);
  }, [filteredOrders, safePage, pageSize]);

  const orderColumns: Column<OrderSummary>[] = [
    { key: "order_request_id", header: "주문 ID", width: "100px", render: (r: OrderSummary) => (
      <code className="text-xs">{r.order_request_id.slice(0, 8)}…</code>
    )},
    { key: "symbol", header: "종목", width: "80px", render: (r: OrderSummary) => (
      r.symbol ? (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/operations/realtime-quotes?symbol=${encodeURIComponent(r.symbol as string)}`);
          }}
          title="실시간 현재가 보기"
          className="text-sm font-medium text-[#3b82f6] hover:text-[#2563eb] hover:underline transition-colors"
        >
          {r.symbol}
        </button>
      ) : (
        <span className="text-sm font-medium text-[#0f172a]">—</span>
      )
    )},
    { key: "instrument_name", header: "종목명", width: "180px", render: (r: OrderSummary) => (
      <span className="block max-w-[180px] truncate text-sm text-[#334155]" title={r.instrument_name ?? undefined}>{r.instrument_name || "—"}</span>
    )},
    { key: "side", header: "매매", width: "80px", render: (r: OrderSummary) => (
      <StatusBadge variant={r.side.toLowerCase() === "buy" ? "success" : "error"}>{getEnumLabel(fieldMap, "side", r.side)}</StatusBadge>
    )},
    { key: "requested_quantity", header: "수량", width: "90px", align: "right" },
    { key: "order_type", header: "주문유형", width: "100px", render: (r: OrderSummary) => (
      <span className="text-sm text-[#334155]">{getEnumLabel(fieldMap, "order_type", r.order_type)}</span>
    )},
    { key: "avg_fill_price", header: "체결가격", width: "110px", align: "right", render: (r: OrderSummary) => formatNumber(r.avg_fill_price) },
    { key: "fill_amount", header: "체결금액", width: "130px", align: "right", render: (r: OrderSummary) => formatNumber(r.fill_amount) },
    { key: "status", header: "상태", width: "110px", render: (r: OrderSummary) => {
      const variants: Record<string, "success" | "warning" | "error" | "info" | "neutral"> = {
        filled: "success",
        submitted: "info",
        partially_filled: "info",
        pending_submit: "warning",
        rejected: "error",
        cancelled: "neutral",
        expired: "neutral",
        acknowledged: "info",
        reconcile_required: "warning",
        draft: "neutral",
        validated: "info",
        cancel_pending: "warning",
        // Legacy / short keys (fixture backward compat)
        pending: "warning",
        partial: "info",
      };
      return <StatusBadge variant={variants[r.status] || "info"}>{getEnumLabel(fieldMap, "order_status", r.status)}</StatusBadge>;
    }},
    { key: "created_at", header: "시각", width: "170px", render: (r: OrderSummary) => formatKstDateTime(r.created_at) },
  ];

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">주문</h1>
        <p className="text-sm text-[#64748b] mt-1">주문 생애주기, 브로커 매핑, 의사결정 이력 조회</p>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Orders List */}
        <div className={selectedOrder ? "col-span-7" : "col-span-12"}>
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-4 mb-4">
            <FilterBar
              searchPlaceholder="심볼 또는 주문 ID 검색..."
              searchValue={searchText}
              onSearchChange={(v) => { setSearchText(v); setCurrentPage(1); }}
              filters={[
                {
                  key: "status",
                  label: "상태",
                  options: [
                    { label: "제출됨", value: "submitted" },
                    { label: "제출 대기", value: "pending_submit" },
                    { label: "확인됨", value: "acknowledged" },
                    { label: "부분 체결", value: "partially_filled" },
                    { label: "체결", value: "filled" },
                    { label: "거부됨", value: "rejected" },
                    { label: "취소 대기", value: "cancel_pending" },
                    { label: "취소됨", value: "cancelled" },
                    { label: "만료", value: "expired" },
                    { label: "조정 필요", value: "reconcile_required" },
                    { label: "검증됨", value: "validated" },
                    { label: "초안", value: "draft" },
                  ],
                  value: statusFilter,
                  onChange: (v) => { setStatusFilter(v); setCurrentPage(1); },
                },
                {
                  key: "side",
                  label: "매매",
                  options: [
                    { label: "매수", value: "buy" },
                    { label: "매도", value: "sell" },
                  ],
                  value: sideFilter,
                  onChange: (v) => { setSideFilter(v); setCurrentPage(1); },
                },
              ]}
              rightSlot={(
                <label className="flex items-center gap-2 text-sm text-[#475569]">
                  <span>조회일</span>
                  <input
                    aria-label="조회일"
                    type="date"
                    value={selectedDate}
                    onChange={(e) => {
                      setSelectedDate(e.target.value || todayKst());
                      setCurrentPage(1);
                    }}
                    className="rounded-lg border border-[#e2e8f0] bg-white px-3 py-2 text-sm text-[#0f172a] focus:outline-none focus:ring-2 focus:ring-[#3b82f6] focus:border-transparent"
                  />
                </label>
              )}
              onClearAll={() => {
                setSearchText("");
                setStatusFilter("");
                setSideFilter("");
                setSelectedDate(todayKst());
                setCurrentPage(1);
              }}
            />
          </div>
          <DataTable
            columns={orderColumns}
            data={pagedOrders}
            idKey="order_request_id"
            currentPage={safePage}
            pageSize={pageSize}
            totalItems={filteredOrders.length}
            onPageChange={setCurrentPage}
            onPageSizeChange={(size) => { setPageSize(size); setCurrentPage(1); }}
            onRowClick={(row) => {
              if (selectedOrder?.order_request_id === row.order_request_id) {
                setSelectedOrder(null);
              } else {
                setSelectedOrder(row);
              }
            }}
            selectedId={selectedOrder?.order_request_id}
            emptyMessage="주문이 없습니다."
          />
        </div>

        {/* Order Detail Panel */}
        {selectedOrder && (
          <div className="col-span-5 space-y-4">
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
              <dl className="space-y-3">
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">주문 ID</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedOrder.order_request_id}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">심볼</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedOrder.symbol ?? "—"}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">매매</dt>
                  <dd><StatusBadge variant={selectedOrder.side.toLowerCase() === "buy" ? "success" : "error"}>{getEnumLabel(fieldMap, "side", selectedOrder.side)}</StatusBadge></dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">수량</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedOrder.requested_quantity}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">주문유형</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{getEnumLabel(fieldMap, "order_type", selectedOrder.order_type)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">체결가격</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{formatNumber(selectedOrder.avg_fill_price)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">체결금액</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{formatNumber(selectedOrder.fill_amount)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">상태</dt>
                  <dd><StatusBadge status={selectedOrder.status}>{getEnumLabel(fieldMap, "order_status", selectedOrder.status)}</StatusBadge></dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">클라이언트 주문 ID</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedOrder.client_order_id}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">생성일</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{formatKstDateTime(selectedOrder.created_at)}</dd>
                </div>
              </dl>
              <div className="mt-4 pt-4 border-t border-[#e2e8f0]">
                <button
                  onClick={() => navigate(`/orders/${selectedOrder.order_request_id}`)}
                  className="w-full text-center text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
                >
                  전체 상세 보기 →
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
