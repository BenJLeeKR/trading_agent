import { useEffect, useMemo, useState } from "react";
import type { ReconciliationRunSummary, BlockingLockStatus, AccountSummary, OrderSummary } from "../types/api";
import { getAccounts, getOrders, getReconciliationRuns, getReconciliationLocks } from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { WarningBanner } from "./common/WarningBanner";
import { FilterBar } from "./common/FilterBar";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import type { Column } from "./common/DataTable";
import { X, CheckCircle, AlertTriangle } from "lucide-react";

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
  const [runs, setRuns] = useState<ReconciliationRunSummary[]>([]);
  const [locks, setLocks] = useState<BlockingLockStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runStatusFilter, setRunStatusFilter] = useState("all");
  const [selectedRun, setSelectedRun] = useState<ReconciliationRunSummary | null>(null);

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
      header: "Date",
      render: (r) => new Date(r.started_at).toLocaleDateString(),
    },
    {
      key: "started_at",
      header: "Time",
      render: (r) => new Date(r.started_at).toLocaleTimeString(),
    },
    {
      key: "status",
      header: "Status",
      render: (r) => <StatusBadge status={r.status} />,
    },
    { key: "order_mismatches", header: "Order Mismatches" },
    { key: "position_mismatches", header: "Position Mismatches" },
  ];

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">정합성 점검</h1>
        <p className="text-sm text-[#64748b] mt-1">불확실한 상태, 정합성 점검 실행 및 활성 잠금을 모니터링합니다</p>
      </div>

      {/* Active lock warning banner (template pattern) */}
      {activeLocks.length > 0 && (
        <WarningBanner
          variant="error"
          title={`활성 차단 잠금 ${activeLocks.length}개`}
          message="거래 작업을 차단할 수 있습니다. 잠금을 해결한 후 새 주문을 제출하세요."
        />
      )}

      {/* Active Locks Section */}
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
                      {new Date(lock.acquired_at).toLocaleTimeString()}
                    </td>
                    <td className="px-4 py-2.5 text-sm text-[#64748b]">
                      {lock.expires_at ? new Date(lock.expires_at).toLocaleTimeString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Reconciliation Runs Section */}
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
                    <dd className="text-sm text-[#0f172a]">{new Date(selectedRun.started_at).toLocaleString()}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-sm text-[#64748b]">완료</dt>
                    <dd className="text-sm text-[#0f172a]">
                      {selectedRun.completed_at ? new Date(selectedRun.completed_at).toLocaleString() : "—"}
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
