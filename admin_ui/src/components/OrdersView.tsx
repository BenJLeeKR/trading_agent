import { useEffect, useMemo, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import type { OrderSummary } from "../types/api";
import { getOrders } from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { FilterBar } from "./common/FilterBar";
import { useEnumMetadata, getEnumLabel } from "../hooks/useEnumMetadata";
import { X } from "lucide-react";
import { formatKstDateTime } from "../lib/utils";

export default function OrdersView() {
  const { fieldMap } = useEnumMetadata();
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sideFilter, setSideFilter] = useState("");
  const [selectedOrder, setSelectedOrder] = useState<OrderSummary | null>(null);
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
    getOrders()
      .then(setOrders)
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "주문을 불러오지 못했습니다";
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
    { key: "order_request_id", header: "주문 ID", width: "100px", render: (r: OrderSummary) => (
      <code className="text-xs">{r.order_request_id.slice(0, 8)}…</code>
    )},
    { key: "symbol", header: "심볼", render: (r: OrderSummary) => (
      <span className="text-sm font-medium text-[#0f172a]">{r.symbol ?? "—"}</span>
    )},
    { key: "instrument_name", header: "종목명", render: (r: OrderSummary) => (
      <span className="text-sm text-[#334155]">{r.instrument_name || "—"}</span>
    )},
    { key: "side", header: "매매", width: "90px", render: (r: OrderSummary) => (
      <StatusBadge variant={r.side.toLowerCase() === "buy" ? "success" : "error"}>{getEnumLabel(fieldMap, "side", r.side)}</StatusBadge>
    )},
    { key: "requested_quantity", header: "수량" },
    { key: "status", header: "상태", render: (r: OrderSummary) => {
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
    { key: "created_at", header: "생성일", render: (r: OrderSummary) => formatKstDateTime(r.created_at) },
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
              onSearchChange={setSearchText}
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
                  onChange: setStatusFilter,
                },
                {
                  key: "side",
                  label: "매매",
                  options: [
                    { label: "매수", value: "buy" },
                    { label: "매도", value: "sell" },
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
          </div>
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
