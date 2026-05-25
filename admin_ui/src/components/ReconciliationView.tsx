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
  getReconciliationSummary,
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

/** 3-값 배지 렌더링: completed → ✅ 완료, started+isActive → 🔄 진행 중, active → 🔴 조치 필요, 그 외 → 📋 과거 이력 */
function getStatusBadge(status: string, isActive: boolean) {
  if (status === "completed") return { text: "✅ 완료", className: "text-green-600" };
  if (status === "started") return { text: "🔄 진행 중", className: "text-blue-600" };
  if (isActive) return { text: "🔴 조치 필요", className: "text-red-600 font-semibold" };
  return { text: "📋 과거 이력", className: "text-gray-400" };
}

export default function ReconciliationView() {
  /* ── Reconciliation runs / locks state ──── */
  const [runs, setRuns] = useState<ReconciliationRunSummary[]>([]);
  const [locks, setLocks] = useState<BlockingLockStatus[]>([]);
  const [runsLocksLoading, setRunsLocksLoading] = useState(true);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [locksError, setLocksError] = useState<string | null>(null);
  const [runStatusFilter, setRunStatusFilter] = useState("all");
  const [selectedRun, setSelectedRun] = useState<ReconciliationRunSummary | null>(null);

  /* ── Historical failed state ────────────── */
  const [showHistoricalFailed, setShowHistoricalFailed] = useState(false);
  const [historicalFailedRuns, setHistoricalFailedRuns] = useState<ReconciliationRunSummary[]>([]);
  const [historicalFailedLoading, setHistoricalFailedLoading] = useState(false);
  const [selectedHistoricalRun, setSelectedHistoricalRun] = useState<ReconciliationRunSummary | null>(null);

  /* ── Reconcile-required state ───────────── */
  const [reconcileOrders, setReconcileOrders] = useState<OrderSummary[]>([]);
  const [positionsByAccount, setPositionsByAccount] = useState<Map<string, PositionSnapshotView[]>>(new Map());
  const [reconcileLoading, setReconcileLoading] = useState(false);
  const [reconcileError, setReconcileError] = useState<string | null>(null);
  const [expandedOrderId, setExpandedOrderId] = useState<string | null>(null);
  const [brokerOrdersMap, setBrokerOrdersMap] = useState<Map<string, BrokerOrderView[]>>(new Map());
  const [brokerLoading, setBrokerLoading] = useState<Set<string>>(new Set());

  /* ── Data loading ───────────────────────── */

  // Load reconciliation runs (active only by default) + locks
  useEffect(() => {
    let cancelled = false;

    async function loadRuns() {
      try {
        // 기본 동작: active_only=true → active issue만 반환
        const runsData = await getReconciliationRuns(undefined, false);
        if (!cancelled) setRuns(runsData);
      } catch (err) {
        if (!cancelled) {
          setRunsError(err instanceof Error ? err.message : "정합성 실행 데이터를 불러오지 못했습니다");
        }
      }
    }

    async function loadLocks() {
      try {
        const locksData = await getReconciliationLocks();
        if (!cancelled) setLocks(locksData);
      } catch (err) {
        if (!cancelled) {
          setLocksError(err instanceof Error ? err.message : "잠금 데이터를 불러오지 못했습니다");
        }
      }
    }

    (async () => {
      setRunsLocksLoading(true);
      setRunsError(null);
      setLocksError(null);
      await Promise.all([loadRuns(), loadLocks()]);
      if (!cancelled) setRunsLocksLoading(false);
    })();

    return () => { cancelled = true; };
  }, []);

  // Load historical failed runs when section is expanded
  useEffect(() => {
    if (!showHistoricalFailed) return;
    let cancelled = false;

    async function loadHistorical() {
      setHistoricalFailedLoading(true);
      try {
        // include_historical=true 로 모든 run 조회 후 historical failed 만 필터링
        const allRuns = await getReconciliationRuns(undefined, true);
        if (!cancelled) {
          setHistoricalFailedRuns(
            allRuns.filter((r) => !r.isActive && r.status !== "completed"),
          );
        }
      } catch {
        if (!cancelled) setHistoricalFailedRuns([]);
      } finally {
        if (!cancelled) setHistoricalFailedLoading(false);
      }
    }

    loadHistorical();
    return () => { cancelled = true; };
  }, [showHistoricalFailed]);

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
    () => locks.filter((l) => l.is_active),
    [locks],
  );

  const filteredRuns = useMemo(() => {
    let result = runStatusFilter === "all"
      ? runs
      : runs.filter((r) => r.status === runStatusFilter);
    return result;
  }, [runs, runStatusFilter]);

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

  /* ── Derived: active issues ─────────────── */

  const recentActiveIssues = useMemo(
    () => runs.filter((r) => r.isActive),
    [runs],
  );

  const historicalFailedCount = useMemo(
    () => runs.filter((r) => !r.isActive && r.status !== "completed").length,
    [runs],
  );

  /* ── Columns ────────────────────────────── */

  const runColumns: Column<ReconciliationRunSummary>[] = [
    {
      key: "reconciliation_run_id",
      header: "Run ID",
      render: (r) => (
        <code className="text-xs">{r.reconciliation_run_id.slice(0, 8)}…</code>
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
    { key: "mismatch_count", header: "Mismatch Count" },
    {
      key: "isActive",
      header: "유형",
      render: (r) => {
        const badge = getStatusBadge(r.status, r.isActive);
        return (
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${badge.className}`}>
            {badge.text}
          </span>
        );
      },
    },
  ];

  /** Historical failed run 전용 컬럼 */
  const historicalColumns: Column<ReconciliationRunSummary>[] = [
    {
      key: "status",
      header: "상태",
      render: (r) => <StatusBadge status={r.status} />,
    },
    {
      key: "completed_at",
      header: "완료 시각",
      render: (r) => (r.completed_at ? formatKstDateTime(r.completed_at) : "—"),
    },
    {
      key: "failure_reason",
      header: "실패 사유",
      render: (r) => (
        <span
          className="text-sm text-[#64748b] max-w-[300px] truncate block"
          title={r.failure_reason ?? ""}
        >
          {r.failure_reason ?? "—"}
        </span>
      ),
    },
    {
      key: "mismatch_count",
      header: "불일치",
      render: (r) => r.mismatch_count,
    },
    {
      key: "summary_error",
      header: "",
      render: (r) => (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setSelectedHistoricalRun(
              selectedHistoricalRun?.reconciliation_run_id === r.reconciliation_run_id ? null : r,
            );
          }}
          className="text-xs text-[#3b82f6] hover:text-[#2563eb] font-medium"
        >
          상세 보기
        </button>
      ),
    },
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
      key: "instrument_name" as any,
      header: "종목명",
      render: (r: ReconcileRequiredCase) => (
        <span className="text-sm text-[#334155]">{r.order.instrument_name || "—"}</span>
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

  return (
    <div className="p-6 space-y-6">
      {/* Page Header (always visible — gives immediate feedback) */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">정합성 점검</h1>
        <p className="text-sm text-[#64748b] mt-1">
          불확실한 상태, 정합성 점검 실행 및 활성 잠금을 모니터링합니다
        </p>
      </div>

      {/* ── Runs / Locks section (section-level loading) ── */}
      {runsLocksLoading ? (
        <LoadingSpinner text="정합성 데이터 로딩 중..." />
      ) : (
        <>
          {/* Individual error banners — one failure does not hide the other section */}
          {runsError && (
            <ErrorBanner message={runsError} onDismiss={() => setRunsError(null)} />
          )}
          {locksError && (
            <ErrorBanner message={locksError} onDismiss={() => setLocksError(null)} />
          )}

          {/* Active lock warning banner */}
          {activeLocks.length > 0 && (
            <WarningBanner
              variant="error"
              title={`활성 차단 잠금 ${activeLocks.length}개`}
              message="거래 작업을 차단할 수 있습니다. 잠금을 해결한 후 새 주문을 제출하세요."
            />
          )}

          {/* ── 1. Active Issues Section ───────────── */}
          {recentActiveIssues.length > 0 ? (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold text-[#0f172a]">
                🔴 조치 필요한 정합성 문제 ({recentActiveIssues.length}건)
              </h2>
              <p className="text-sm text-gray-500 mb-2">
                이 정합성 run은 아직 해결되지 않은 주문과 연결되어 있습니다. 조치가 필요합니다.
              </p>
              <div className="bg-white rounded-xl border border-[#fca5a5] overflow-hidden">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-[#fee2e2] bg-[#fef2f2]">
                      {["Run ID", "시작", "Status", "불일치 건수", ""].map((h) => (
                        <th
                          key={h}
                          className="px-4 py-2.5 text-left text-xs font-medium text-[#991b1b] whitespace-nowrap"
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#fee2e2]">
                    {recentActiveIssues.map((run) => (
                      <tr key={run.reconciliation_run_id} className="hover:bg-[#fef2f2]">
                        <td className="px-4 py-2.5">
                          <code className="text-xs text-[#991b1b]">{run.reconciliation_run_id.slice(0, 8)}…</code>
                        </td>
                        <td className="px-4 py-2.5 text-sm text-[#991b1b]">
                          {formatKstDateTime(run.started_at)}
                        </td>
                        <td className="px-4 py-2.5">
                          <StatusBadge status={run.status} />
                        </td>
                        <td className={`px-4 py-2.5 text-sm font-semibold ${run.mismatch_count > 0 ? "text-[#dc2626]" : "text-[#991b1b]"}`}>
                          {run.mismatch_count}
                        </td>
                        <td className="px-4 py-2.5">
                          <button
                            type="button"
                            onClick={() =>
                              setSelectedRun(
                                selectedRun?.reconciliation_run_id === run.reconciliation_run_id ? null : run,
                              )
                            }
                            className="text-xs text-[#3b82f6] hover:text-[#2563eb] font-medium"
                          >
                            상세 보기
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="bg-green-50 border border-green-200 rounded p-3 mb-4">
              <p className="text-green-700">✅ 현재 해결되지 않은 정합성 문제가 없습니다.</p>
              {historicalFailedCount > 0 && (
                <p className="text-green-600 text-sm mt-1">
                  과거 실패 이력 {historicalFailedCount}건은 아래에서 확인할 수 있습니다.
                </p>
              )}
            </div>
          )}

          {/* ── 2. Active Locks Section ────────────── */}
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
                      {["계정", "전략", "Side", "사유", "상태", "획득 시각", "실행 ID"].map((h) => (
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
                    {locks.map((lock, idx) => (
                      <tr key={lock.account_id + lock.locked_by_run_id + idx} className="hover:bg-[#f8fafc]">
                        <td className="px-4 py-2.5">
                          <span className="text-sm font-medium text-[#0f172a]">{lock.account_id}</span>
                        </td>
                        <td className="px-4 py-2.5">
                          <span className="text-sm text-[#334155]">{lock.strategy_id}</span>
                        </td>
                        <td className="px-4 py-2.5 text-sm text-[#64748b]">{lock.side}</td>
                        <td className="px-4 py-2.5 text-sm text-[#64748b]">{lock.reason}</td>
                        <td className="px-4 py-2.5">
                          <StatusBadge variant={!lock.is_active ? "neutral" : "error"}>
                            {!lock.is_active ? "만료" : "활성"}
                          </StatusBadge>
                        </td>
                        <td className="px-4 py-2.5 text-sm text-[#64748b]">
                          {formatKstDateTime(lock.locked_at)}
                        </td>
                        <td className="px-4 py-2.5 text-sm text-[#64748b]">
                          {lock.locked_by_run_id}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* ── 3. Historical Failed Section (collapsible) ── */}
          <div className="space-y-3">
            <button
              type="button"
              onClick={() => setShowHistoricalFailed(!showHistoricalFailed)}
              className="flex items-center gap-2 w-full text-left"
            >
              <span className="text-lg font-semibold text-[#0f172a]">
                {showHistoricalFailed ? "▼" : "▶"}{" "}
                📋 과거 실패 이력 ({historicalFailedCount}건)
              </span>
            </button>

            {showHistoricalFailed && (
              <>
                {historicalFailedLoading ? (
                  <LoadingSpinner text="과거 실패 이력 로딩 중..." />
                ) : historicalFailedRuns.length === 0 ? (
                  <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
                    <p className="text-sm text-[#94a3b8]">과거 실패 이력이 없습니다.</p>
                  </div>
                ) : (
                  <div className="grid grid-cols-12 gap-6">
                    <div className={selectedHistoricalRun ? "col-span-7" : "col-span-12"}>
                      <div className="bg-white rounded-xl border border-[#e2e8f0] overflow-hidden">
                        <table className="w-full">
                          <thead>
                            <tr className="border-b border-[#e2e8f0] bg-[#f8fafc]">
                              {["상태", "완료 시각", "실패 사유", "불일치", ""].map((h) => (
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
                            {historicalFailedRuns.map((run) => (
                              <tr key={run.reconciliation_run_id} className="hover:bg-[#f8fafc]">
                                <td className="px-4 py-2.5">
                                  <StatusBadge status={run.status} />
                                </td>
                                <td className="px-4 py-2.5 text-sm text-[#64748b]">
                                  {run.completed_at ? formatKstDateTime(run.completed_at) : "—"}
                                </td>
                                <td className="px-4 py-2.5">
                                  <span
                                    className="text-sm text-[#64748b] max-w-[300px] truncate block"
                                    title={run.failure_reason ?? ""}
                                  >
                                    {run.failure_reason ?? "—"}
                                  </span>
                                </td>
                                <td className="px-4 py-2.5 text-sm text-[#64748b]">
                                  {run.mismatch_count}
                                </td>
                                <td className="px-4 py-2.5">
                                  <button
                                    type="button"
                                    onClick={() =>
                                      setSelectedHistoricalRun(
                                        selectedHistoricalRun?.reconciliation_run_id === run.reconciliation_run_id
                                          ? null
                                          : run,
                                      )
                                    }
                                    className="text-xs text-[#3b82f6] hover:text-[#2563eb] font-medium"
                                  >
                                    상세 보기
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    {/* Historical Run Detail Panel */}
                    {selectedHistoricalRun && (
                      <div className="col-span-5 space-y-4">
                        <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
                          <div className="flex items-center justify-between mb-4">
                            <h3 className="text-lg font-semibold text-[#0f172a]">실행 상세</h3>
                            <button
                              onClick={() => setSelectedHistoricalRun(null)}
                              className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
                            >
                              <X className="h-5 w-5" />
                            </button>
                          </div>
                          <dl className="space-y-3">
                            <div className="flex justify-between">
                              <dt className="text-sm text-[#64748b]">실행 ID</dt>
                              <dd className="text-sm font-mono text-[#0f172a]">{selectedHistoricalRun.reconciliation_run_id}</dd>
                            </div>
                            <div className="flex justify-between">
                              <dt className="text-sm text-[#64748b]">상태</dt>
                              <dd><StatusBadge status={selectedHistoricalRun.status} /></dd>
                            </div>
                            <div className="flex justify-between">
                              <dt className="text-sm text-[#64748b]">실패 사유</dt>
                              <dd className="text-sm text-[#0f172a] font-medium">{selectedHistoricalRun.failure_reason ?? "—"}</dd>
                            </div>
                            <div className="flex justify-between">
                              <dt className="text-sm text-[#64748b]">완료 시각</dt>
                              <dd className="text-sm text-[#0f172a]">
                                {selectedHistoricalRun.completed_at ? formatKstDateTime(selectedHistoricalRun.completed_at) : "—"}
                              </dd>
                            </div>
                            <div className="flex justify-between">
                              <dt className="text-sm text-[#64748b]">불일치 건수</dt>
                              <dd className={`text-sm font-semibold ${selectedHistoricalRun.mismatch_count > 0 ? "text-[#dc2626]" : "text-[#0f172a]"}`}>
                                {selectedHistoricalRun.mismatch_count}
                              </dd>
                            </div>
                          </dl>

                          {/* 상세 오류 메시지 */}
                          {selectedHistoricalRun.summary_error && (
                            <div className="mt-4 pt-4 border-t border-[#e2e8f0]">
                              <h4 className="text-xs font-medium text-[#64748b] mb-1">상세 오류 메시지</h4>
                              <pre className="text-xs text-[#991b1b] bg-[#fef2f2] p-2 rounded whitespace-pre-wrap">
                                {selectedHistoricalRun.summary_error}
                              </pre>
                            </div>
                          )}

                          {/* 기록용 안내 */}
                          <div className="mt-4 pt-4 border-t border-[#e2e8f0] flex items-start gap-2">
                            <span className="text-sm text-gray-400">📋</span>
                            <span className="text-sm text-gray-400">
                              이 run의 연결 주문은 모두 정리되었습니다. 감사 이력으로만 참고하세요.
                            </span>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>

          {/* ── 4. All Runs Section (with filter) ── */}
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

            {/* Runs table 상단 설명 */}
            <p className="text-xs text-gray-400 mb-2">
              🔴 Active: 조치 필요 / 📋 과거 이력: 참고용 (연결 주문 정리됨) / ✅ 완료: 정상
            </p>

            {/* Runs table + detail side-by-side */}
            <div className="grid grid-cols-12 gap-6">
              <div className={selectedRun ? "col-span-7" : "col-span-12"}>
                <DataTable
                  columns={runColumns}
                  data={filteredRuns}
                  idKey="reconciliation_run_id"
                  onRowClick={(row) =>
                    setSelectedRun(
                      selectedRun?.reconciliation_run_id === row.reconciliation_run_id ? null : row,
                    )
                  }
                  selectedId={selectedRun?.reconciliation_run_id}
                  rowClassName={(row) =>
                    !row.isActive && row.status !== "completed" ? "opacity-50" : ""
                  }
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
                        <dd className="text-sm font-mono text-[#0f172a]">{selectedRun.reconciliation_run_id}</dd>
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
                        <dt className="text-sm text-[#64748b]">불일치 건수</dt>
                        <dd className={`text-sm font-semibold ${selectedRun.mismatch_count > 0 ? "text-[#dc2626]" : "text-[#0f172a]"}`}>
                          {selectedRun.mismatch_count}
                        </dd>
                      </div>
                    </dl>

                    {/* Status footer */}
                    {selectedRun.status === "completed" &&
                      selectedRun.mismatch_count === 0 && (
                        <div className="mt-4 pt-4 border-t border-[#e2e8f0] flex items-center gap-2">
                          <CheckCircle className="h-4 w-4 text-[#16a34a]" />
                          <span className="text-sm text-[#16a34a]">모든 포지션이 일치합니다.</span>
                        </div>
                      )}
                    {selectedRun.mismatch_count > 0 && (
                      <div className="mt-4 pt-4 border-t border-[#e2e8f0] flex items-center gap-2">
                        <AlertTriangle className="h-4 w-4 text-[#d97706]" />
                        <span className="text-sm text-[#d97706]">불일치 항목을 검토해야 합니다.</span>
                      </div>
                    )}

                    {selectedRun.summary_error && (
                      <div className="mt-4 pt-4 border-t border-[#e2e8f0]">
                        <h4 className="text-xs font-medium text-[#64748b] mb-1">오류 메시지</h4>
                        <pre className="text-xs text-[#991b1b] bg-[#fef2f2] p-2 rounded whitespace-pre-wrap">
                          {selectedRun.summary_error}
                        </pre>
                      </div>
                    )}

                    {/* Historical failed 설명 */}
                    {!selectedRun.isActive && selectedRun.status !== "completed" && (
                      <div className="mt-4 pt-4 border-t border-[#e2e8f0] flex items-start gap-2">
                        <span className="text-sm text-gray-400">📋</span>
                        <span className="text-sm text-gray-400">
                          이 run의 연결 주문은 모두 정리되었습니다. 감사 이력으로만 참고하세요.
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* ── Reconcile-required section (section-level loading) ── */}
      {reconcileLoading ? (
        <LoadingSpinner text="조정 필요 주문 로딩 중..." />
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-[#0f172a]">
              조정 필요 주문
            </h2>
          </div>

          {/* Summary card — semantics-safe: never show misleading "0" while loading/error */}
          {!reconcileError && reconcileCases.length > 0 && (
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

          {/* Partial data warning — data exists but some accounts failed */}
          {reconcileError && reconcileCases.length > 0 && (
            <WarningBanner
              variant="warning"
              title="데이터 일부 누락"
              message="일부 계정의 포지션 데이터를 불러오지 못했습니다. 표시된 정보는 불완전할 수 있습니다."
            />
          )}

          {/* Error banner (no data at all) */}
          {reconcileError && reconcileCases.length === 0 && (
            <ErrorBanner
              message={reconcileError}
              onDismiss={() => setReconcileError(null)}
            />
          )}

          {/* Warning banner when many unreconciled orders */}
          {reconcileCases.length > 5 && (
            <WarningBanner
              variant="warning"
              title={`조정 필요 주문 ${reconcileCases.length}건`}
              message="포지션 반영 여부를 확인하고 필요 시 수동 조정하세요."
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
                    {["심볼", "종목명", "상태", "수량", "주문가", "포지션 반영", "해석", ""].map(
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
                          <span className="text-sm text-[#334155]">{rc.order.instrument_name || "—"}</span>
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
                          <td colSpan={8} className="px-4 py-3 bg-[#f8fafc]">
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
      )}
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
