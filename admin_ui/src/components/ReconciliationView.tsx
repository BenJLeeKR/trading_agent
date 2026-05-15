import { useEffect, useMemo, useState, Fragment } from "react";
import { formatKstDateTime, formatKrw } from "@/lib/utils";
import type {
  ReconciliationRunSummary,
  BlockingLockStatus,
  AccountSummary,
  OrderSummary,
  PositionSnapshotView,
  BrokerOrderView,
} from "../types/api";
import {
  getAccounts,
  getOrders,
  getPositions,
  getBrokerOrders,
  getReconciliationRuns,
  getReconciliationLocks,
} from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { WarningBanner } from "./common/WarningBanner";
import { FilterBar } from "./common/FilterBar";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import type { Column } from "./common/DataTable";
import { X, CheckCircle, AlertTriangle, ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import {
  deriveReconcileRequiredCases,
  type ReconcileRequiredCase,
} from "../lib/reconcileRequired";

const RUN_STATUSES = [
  "all",
  "completed",
  "running",
  "reconcile_required",
  "failed",
] as const;

function formatStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    all: "전체",
    completed: "완료",
    running: "실행 중",
    reconcile_required: "정합성 필요",
    failed: "실패",
  };
  return labels[status] ?? status;
}

export default function ReconciliationView() {
  /* ── Reconciliation runs / locks state ──── */
  const [runs, setRuns] = useState<ReconciliationRunSummary[]>([]);
  const [locks, setLocks] = useState<BlockingLockStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runStatusFilter, setRunStatusFilter] = useState("all");
  const [selectedRun, setSelectedRun] = useState<ReconciliationRunSummary | null>(null);

  /* ── Reconcile-required state ───────────── */
  const [reconcileOrders, setReconcileOrders] = useState<OrderSummary[]>([]);
  const [positionsByAccount, setPositionsByAccount] = useState<Map<string, PositionSnapshotView[]>>(new Map());
  const [reconcileLoading, setReconcileLoading] = useState(false);
  const [reconcileError, setReconcileError] = useState<string | null>(null);
  const [expandedOrderId, setExpandedOrderId] = useState<string | null>(null);
  const [brokerOrdersMap, setBrokerOrdersMap] = useState<Map<string, BrokerOrderView[]>>(new Map());
  const [brokerLoading, setBrokerLoading] = useState<Set<string>>(new Set());

  /* ── Data loading ───────────────────────── */

  // Load reconciliation runs + locks (existing behaviour)
  useEffect(() => {
    setLoading(true);
    setError(null);

    // Backend /reconciliation endpoints require an account_id, which we cannot
    // derive from /orders alone (OrderSummary has no client_id).
    // Show empty state until a proper account selection mechanism is added.
    setRuns([]);
    setLocks([]);
    setLoading(false);
  }, []);

  // Load reconcile_required orders + positions
  useEffect(() => {
    let cancelled = false;

    async function load() {
      setReconcileLoading(true);
      setReconcileError(null);

      try {
        // Step 1: fetch reconcile_required orders
        const orders = await getOrders("reconcile_required");
        if (cancelled) return;
        setReconcileOrders(orders);

        // Step 2: collect unique account IDs
        const accountIds = new Set(orders.map((o) => o.account_id));

        // Step 3: fetch positions for each account (parallel)
        const entries = await Promise.all(
          Array.from(accountIds).map(async (accountId) => {
            const positions = await getPositions(accountId);
            return [accountId, positions] as const;
          }),
        );
        if (cancelled) return;

        const posMap = new Map<string, PositionSnapshotView[]>();
        for (const [accountId, positions] of entries) {
          posMap.set(accountId, positions);
        }
        setPositionsByAccount(posMap);
      } catch (err: unknown) {
        if (!cancelled) {
          const msg =
            err instanceof Error
              ? err.message
              : "reconcile_required 데이터를 불러오지 못했습니다";
          setReconcileError(msg);
        }
      } finally {
        if (!cancelled) setReconcileLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  /* ── Derived data ───────────────────────── */

  const activeLocks = useMemo(
    () => locks.filter((l) => !l.is_expired),
    [locks],
  );

  const filteredRuns = useMemo(
    () =>
      runStatusFilter === "all"
        ? runs
        : runs.filter((r) => r.status === runStatusFilter),
    [runs, runStatusFilter],
  );

  /** Reconcile-required cases derived from orders + positions */
  const reconcileCases = useMemo(
    () => deriveReconcileRequiredCases(reconcileOrders, positionsByAccount),
    [reconcileOrders, positionsByAccount],
  );

  /** Summary card data */
  const summaryCard = useMemo(() => {
    const total = reconcileCases.length;
    const reflected = reconcileCases.filter((c) => c.positionReflected).length;
    return { total, reflected };
  }, [reconcileCases]);

  /* ── Broker info lazy loader ────────────── */

  async function handleToggleBrokerInfo(orderId: string) {
    if (expandedOrderId === orderId) {
      setExpandedOrderId(null);
      return;
    }

    // If already fetched, just expand
    if (brokerOrdersMap.has(orderId)) {
      setExpandedOrderId(orderId);
      return;
    }

    setExpandedOrderId(orderId);
    setBrokerLoading((prev) => new Set(prev).add(orderId));

    try {
      const brokerOrders = await getBrokerOrders(orderId);
      setBrokerOrdersMap((prev) => {
        const next = new Map(prev);
        next.set(orderId, brokerOrders);
        return next;
      });
    } catch {
      // Silently fail — broker info is supplementary
      setBrokerOrdersMap((prev) => {
        const next = new Map(prev);
        next.set(orderId, []);
        return next;
      });
    } finally {
      setBrokerLoading((prev) => {
        const next = new Set(prev);
        next.delete(orderId);
        return next;
      });
    }
  }

  /* ── Columns ────────────────────────────── */

  const runColumns: Column<ReconciliationRunSummary>[] = [
    {
      key: "run_id",
      header: "Run ID",
      render: (r) => (
        <code className="text-xs">{r.run_id.slice(0, 8)}…</code>
      ),
    },
    {
      key: "started_at",
      header: "시작",
      render: (r) => formatKstDateTime(r.started_at),
    },
    {
      key: "status",
      header: "Status",
      render: (r) => <StatusBadge status={r.status} />,
    },
    { key: "order_mismatches", header: "Order Mismatches" },
    { key: "position_mismatches", header: "Position Mismatches" },
  ];

  const reconcileColumns: Column<ReconcileRequiredCase>[] = [
    {
      key: "order" as any,
      header: "심볼",
      render: (r: ReconcileRequiredCase) => (
        <span className="font-medium text-[#0f172a]">{r.order.symbol ?? "—"}</span>
      ),
    },
    {
      key: "order" as any,
      header: "상태",
      render: (r: ReconcileRequiredCase) => (
        <StatusBadge status={r.order.status} />
      ),
    },
    {
      key: "order" as any,
      header: "수량",
      render: (r: ReconcileRequiredCase) => (
        <span>{r.order.requested_quantity}</span>
      ),
    },
    {
      key: "order" as any,
      header: "주문가",
      render: (r: ReconcileRequiredCase) => (
        <span className="font-mono text-xs">
          {formatKrw(r.order.requested_price)}
        </span>
      ),
    },
    {
      key: "positionReflected",
      header: "포지션 반영",
      render: (r: ReconcileRequiredCase) => (
        <StatusBadge
          variant={r.positionReflected ? "success" : "neutral"}
        >
          {r.positionReflected ? "반영됨" : "미반영"}
        </StatusBadge>
      ),
    },
    {
      key: "interpretiveText",
      header: "해석",
      render: (r: ReconcileRequiredCase) => (
        <span
          className={`text-xs ${
            r.variant === "info" ? "text-[#2563eb]" : "text-[#d97706]"
          }`}
        >
          {r.interpretiveText}
        </span>
      ),
    },
    {
      key: "order" as any,
      header: "",
      render: (r: ReconcileRequiredCase) => (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            handleToggleBrokerInfo(r.order.order_request_id);
          }}
          className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
          title="브로커 정보 보기"
        >
          {expandedOrderId === r.order.order_request_id ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </button>
      ),
    },
  ];

  /* ── Render ─────────────────────────────── */

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">정합성 점검</h1>
        <p className="text-sm text-[#64748b] mt-1">
          불확실한 상태, 정합성 점검 실행 및 활성 잠금을 모니터링합니다
        </p>
      </div>

      {/* Active lock warning banner (template pattern) */}
      {activeLocks.length > 0 && (
        <WarningBanner
          variant="error"
          title={`활성 차단 잠금 ${activeLocks.length}개`}
          message="거래 작업을 차단할 수 있습니다. 잠금을 해결한 후 새 주문을 제출하세요."
        />
      )}

      {/* ── Reconcile-required section ──────── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">
            조정 필요 주문
          </h2>
          {reconcileLoading && (
            <RefreshCw className="h-4 w-4 text-[#64748b] animate-spin" />
          )}
        </div>

        {/* Summary card */}
        {reconcileCases.length > 0 && (
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-4">
              <p className="text-xs text-[#64748b]">조정 필요 주문</p>
              <p className="text-2xl font-semibold text-[#0f172a] mt-1">
                {summaryCard.total}
              </p>
            </div>
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-4">
              <p className="text-xs text-[#64748b]">포지션 반영됨</p>
              <p className="text-2xl font-semibold text-[#0f172a] mt-1">
                {summaryCard.reflected}
              </p>
            </div>
          </div>
        )}

        {/* Warning banner when many unreconciled orders */}
        {reconcileCases.length > 5 && (
          <WarningBanner
            variant="warning"
            title={`조정 필요 주문 ${reconcileCases.length}건`}
            message="포지션 반영 여부를 확인하고 필요 시 수동 조정하세요."
          />
        )}

        {/* Error banner */}
        {reconcileError && (
          <ErrorBanner
            message={reconcileError}
            onDismiss={() => setReconcileError(null)}
          />
        )}

        {/* Reconcile-required table */}
        {reconcileCases.length === 0 && !reconcileLoading ? (
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
            <p className="text-sm text-[#94a3b8]">
              {reconcileError
                ? "데이터를 불러올 수 없습니다."
                : "조정이 필요한 주문이 없습니다."}
            </p>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-[#e2e8f0] overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[#e2e8f0] bg-[#f8fafc]">
                  {["심볼", "상태", "수량", "주문가", "포지션 반영", "해석", ""].map(
                    (h) => (
                      <th
                        key={h}
                        className="px-4 py-2.5 text-left text-xs font-medium text-[#64748b] whitespace-nowrap"
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e2e8f0]">
                {reconcileCases.map((rc) => (
                  <Fragment key={rc.order.order_request_id}>
                    <tr className="hover:bg-[#f8fafc]">
                      <td className="px-4 py-2.5 text-sm font-medium text-[#0f172a]">
                        {rc.order.symbol ?? "—"}
                      </td>
                      <td className="px-4 py-2.5">
                        <StatusBadge status={rc.order.status} />
                      </td>
                      <td className="px-4 py-2.5 text-sm text-[#64748b]">
                        {rc.order.requested_quantity}
                      </td>
                      <td className="px-4 py-2.5 text-sm font-mono text-[#64748b]">
                        {formatKrw(rc.order.requested_price)}
                      </td>
                      <td className="px-4 py-2.5">
                        <StatusBadge
                          variant={rc.positionReflected ? "success" : "neutral"}
                        >
                          {rc.positionReflected ? "반영됨" : "미반영"}
                        </StatusBadge>
                      </td>
                      <td className="px-4 py-2.5">
                        <span
                          className={`text-xs ${
                            rc.variant === "info"
                              ? "text-[#2563eb]"
                              : "text-[#d97706]"
                          }`}
                        >
                          {rc.interpretiveText}
                        </span>
                      </td>
                      <td className="px-4 py-2.5">
                        <button
                          type="button"
                          onClick={() =>
                            handleToggleBrokerInfo(rc.order.order_request_id)
                          }
                          className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
                          title="브로커 정보 보기"
                        >
                          {expandedOrderId === rc.order.order_request_id ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                        </button>
                      </td>
                    </tr>
                    {/* Expanded broker info row */}
                    {expandedOrderId === rc.order.order_request_id && (
                      <tr key={`${rc.order.order_request_id}-broker`}>
                        <td colSpan={7} className="px-4 py-3 bg-[#f8fafc]">
                          <BrokerInfoPanel
                            orderId={rc.order.order_request_id}
                            brokerOrders={brokerOrdersMap.get(
                              rc.order.order_request_id,
                            )}
                            loading={brokerLoading.has(
                              rc.order.order_request_id,
                            )}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Active Locks Section ────────────── */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold text-[#0f172a]">활성 잠금</h2>
        {locks.length === 0 ? (
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
            <p className="text-sm text-[#94a3b8]">차단 잠금이 없습니다.</p>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-[#e2e8f0] overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[#e2e8f0] bg-[#f8fafc]">
                  {["심볼", "유형", "전략", "상태", "획득 시각", "만료 시각"].map((h) => (
                    <th
                      key={h}
                      className="px-4 py-2.5 text-left text-xs font-medium text-[#64748b] whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e2e8f0]">
                {locks.map((lock) => (
                  <tr key={lock.lock_id} className="hover:bg-[#f8fafc]">
                    <td className="px-4 py-2.5 text-sm font-medium text-[#0f172a]">{lock.symbol}</td>
                    <td className="px-4 py-2.5 text-sm text-[#64748b]">{lock.lock_type}</td>
                    <td className="px-4 py-2.5 text-sm text-[#64748b]">{lock.strategy_code}</td>
                    <td className="px-4 py-2.5">
                      <StatusBadge variant={lock.is_expired ? "neutral" : "error"}>
                        {lock.is_expired ? "만료" : "활성"}
                      </StatusBadge>
                    </td>
                    <td className="px-4 py-2.5 text-sm text-[#64748b]">
                      {formatKstDateTime(lock.acquired_at)}
                    </td>
                    <td className="px-4 py-2.5 text-sm text-[#64748b]">
                      {lock.expires_at ? formatKstDateTime(lock.expires_at) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Reconciliation Runs Section ─────── */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold text-[#0f172a]">정합성 점검 실행</h2>

        {/* Filter pills */}
        <div className="flex items-center gap-2">
          {RUN_STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                runStatusFilter === s
                  ? "bg-[#3b82f6] text-white"
                  : "bg-white text-[#64748b] border border-[#e2e8f0] hover:bg-[#f8fafc]"
              }`}
              onClick={() => {
                setRunStatusFilter(s);
                setSelectedRun(null);
              }}
            >
              {formatStatusLabel(s)}
            </button>
          ))}
        </div>

        {/* Runs table + detail side-by-side */}
        <div className="grid grid-cols-12 gap-6">
          <div className={selectedRun ? "col-span-7" : "col-span-12"}>
            <DataTable
              columns={runColumns}
              data={filteredRuns}
              idKey="run_id"
              onRowClick={(row) =>
                setSelectedRun(
                  selectedRun?.run_id === row.run_id ? null : row,
                )
              }
              selectedId={selectedRun?.run_id}
              emptyMessage="정합성 점검 실행 기록이 없습니다."
            />
          </div>

          {/* Run Detail Panel */}
          {selectedRun && (
            <div className="col-span-5 space-y-4">
              <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold text-[#0f172a]">실행 상세</h3>
                  <button
                    onClick={() => setSelectedRun(null)}
                    className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
                <dl className="space-y-3">
                  <div className="flex justify-between">
                    <dt className="text-sm text-[#64748b]">실행 ID</dt>
                    <dd className="text-sm font-mono text-[#0f172a]">{selectedRun.run_id}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-sm text-[#64748b]">상태</dt>
                    <dd><StatusBadge status={selectedRun.status} /></dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-sm text-[#64748b]">시작</dt>
                    <dd className="text-sm text-[#0f172a]">{formatKstDateTime(selectedRun.started_at)}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-sm text-[#64748b]">완료</dt>
                    <dd className="text-sm text-[#0f172a]">
                      {selectedRun.completed_at ? formatKstDateTime(selectedRun.completed_at) : "—"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-sm text-[#64748b]">주문 불일치</dt>
                    <dd className={`text-sm font-semibold ${selectedRun.order_mismatches > 0 ? "text-[#dc2626]" : "text-[#0f172a]"}`}>
                      {selectedRun.order_mismatches}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-sm text-[#64748b]">포지션 불일치</dt>
                    <dd className={`text-sm font-semibold ${selectedRun.position_mismatches > 0 ? "text-[#dc2626]" : "text-[#0f172a]"}`}>
                      {selectedRun.position_mismatches}
                    </dd>
                  </div>
                </dl>

                {/* Status footer */}
                {selectedRun.status === "completed" &&
                  selectedRun.order_mismatches === 0 &&
                  selectedRun.position_mismatches === 0 && (
                    <div className="mt-4 pt-4 border-t border-[#e2e8f0] flex items-center gap-2">
                      <CheckCircle className="h-4 w-4 text-[#16a34a]" />
                      <span className="text-sm text-[#16a34a]">모든 포지션이 일치합니다.</span>
                    </div>
                  )}
                {(selectedRun.order_mismatches > 0 ||
                  selectedRun.position_mismatches > 0) && (
                  <div className="mt-4 pt-4 border-t border-[#e2e8f0] flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 text-[#d97706]" />
                    <span className="text-sm text-[#d97706]">불일치 항목을 검토해야 합니다.</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Broker Info Panel (sub-component) ────── */

function BrokerInfoPanel({
  orderId,
  brokerOrders,
  loading,
}: {
  orderId: string;
  brokerOrders: BrokerOrderView[] | undefined;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-[#64748b]">
        <RefreshCw className="h-3 w-3 animate-spin" />
        브로커 정보 로딩 중...
      </div>
    );
  }

  if (!brokerOrders || brokerOrders.length === 0) {
    return (
      <p className="text-sm text-[#94a3b8]">브로커 주문 정보가 없습니다.</p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-[#64748b]">
        브로커 주문 ({brokerOrders.length}건)
      </p>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[#e2e8f0]">
            <th className="px-2 py-1 text-left font-medium text-[#64748b]">브로커</th>
            <th className="px-2 py-1 text-left font-medium text-[#64748b]">Native ID</th>
            <th className="px-2 py-1 text-left font-medium text-[#64748b]">상태</th>
            <th className="px-2 py-1 text-left font-medium text-[#64748b]">최종 동기화</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#e2e8f0]">
          {brokerOrders.map((bo) => (
            <tr key={bo.broker_order_id}>
              <td className="px-2 py-1 text-[#0f172a]">{bo.broker_name}</td>
              <td className="px-2 py-1 font-mono text-[#64748b]">
                {bo.broker_native_order_id ?? "—"}
              </td>
              <td className="px-2 py-1">
                <StatusBadge status={bo.broker_status} />
              </td>
              <td className="px-2 py-1 text-[#64748b]">
                {bo.last_synced_at
                  ? formatKstDateTime(bo.last_synced_at)
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

