import { useEffect, useMemo, useState } from "react";
import type { ReconciliationRunSummary, BlockingLockStatus, AccountSummary, OrderSummary } from "../types/api";
import { getAccounts, getOrders, getReconciliationRuns, getReconciliationLocks } from "../api/client";
import { DataTable } from "./common/DataTable";
import { Panel } from "./common/Panel";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import type { Column } from "./common/DataTable";
import { Lock, AlertTriangle, CheckCircle, X } from "lucide-react";

const RUN_STATUSES = [
  "all",
  "completed",
  "running",
  "reconcile_required",
  "failed",
] as const;

function formatStatusLabel(status: string): string {
  if (status === "all") return "All";
  return status
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/* ── DetailRow (template pattern) ── */
function DetailRow({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="detail-row">
      <span className="detail-row-label">{label}</span>
      <span
        className="detail-row-value"
        style={{ color: valueColor ?? "var(--text-primary)" }}
      >
        {value}
      </span>
    </div>
  );
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

    // Phase 1: get orders to obtain a client_id (temporary heuristic)
    getOrders()
      .then((orders: OrderSummary[]) => {
        if (orders.length === 0) {
          // No orders → no client_id available; show empty state
          setRuns([]);
          setLocks([]);
          return;
        }
        const clientId = orders[0].client_id;
        // Phase 2: use client_id to fetch accounts, then get the first account_id
        return getAccounts(clientId).then((accounts: AccountSummary[]) => {
          const accountId = accounts.length > 0 ? accounts[0].account_id : undefined;
          // Phase 3: fetch reconciliation data scoped to the account
          return Promise.all([
            accountId
              ? getReconciliationRuns(accountId)
              : Promise.resolve<ReconciliationRunSummary[]>([]),
            accountId
              ? getReconciliationLocks(accountId)
              : Promise.resolve<BlockingLockStatus[]>([]),
          ]);
        });
      })
      .then((result) => {
        if (result) {
          const [r, l] = result as [ReconciliationRunSummary[], BlockingLockStatus[]];
          setRuns(r);
          setLocks(l);
        }
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Failed to load reconciliation data";
        setError(msg);
      })
      .finally(() => setLoading(false));
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
      label: "Run ID",
      render: (r) => (
        <code style={{ fontSize: "0.6875rem" }}>{r.run_id.slice(0, 8)}…</code>
      ),
    },
    {
      key: "started_at",
      label: "Date",
      render: (r) => new Date(r.started_at).toLocaleDateString(),
    },
    {
      key: "started_at",
      label: "Time",
      render: (r) => new Date(r.started_at).toLocaleTimeString(),
    },
    {
      key: "status",
      label: "Status",
      render: (r) => <StatusBadge status={r.status} />,
    },
    { key: "order_mismatches", label: "Order Mismatches" },
    { key: "position_mismatches", label: "Position Mismatches" },
  ];

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  return (
    <section>
      <div className="page-header">
        <h2>Reconciliation</h2>
        <p>Reconciliation runs & lock management</p>
      </div>

      {/* Active lock warning banner (template pattern) */}
      {activeLocks.length > 0 && (
        <div
          className="warning-banner warning-banner--error"
          style={{ marginBottom: "1rem" }}
        >
          <div className="warning-banner-content">
            <Lock size={15} style={{ flexShrink: 0, marginTop: "0.1rem" }} />
            <div>
              <span className="warning-banner-strong">
                {activeLocks.length} Active Blocking Lock{activeLocks.length !== 1 ? "s" : ""}
              </span>
              <br />
              <span className="warning-banner-body">
                These may block trading operations. Resolve locks before submitting new orders.
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Side-by-side layout (template pattern) */}
      <div className="split-layout" style={{ alignItems: "flex-start" }}>
        {/* Left column: runs + unmatched */}
        <div className="split-main">
          {/* Filter bar */}
          <div className="filter-bar">
            <div className="filter-group" role="group" aria-label="Status">
              {RUN_STATUSES.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`pill-btn${runStatusFilter === s ? " pill-btn--active" : ""}`}
                  onClick={() => {
                    setRunStatusFilter(s);
                    setSelectedRun(null);
                  }}
                >
                  {formatStatusLabel(s)}
                </button>
              ))}
            </div>
          </div>

          {/* Runs table */}
          <Panel title="Reconciliation Runs">
            <DataTable
              columns={runColumns}
              data={filteredRuns}
              keyField="run_id"
              onRowClick={(row) =>
                setSelectedRun(
                  selectedRun?.run_id === row.run_id ? null : row,
                )
              }
              emptyMessage="No reconciliation runs found."
            />
          </Panel>

          {/* Unmatched Positions table (template pattern) */}
          <div className="card-panel" style={{ marginTop: "1rem" }}>
            <div className="card-panel-header">
              <span className="card-panel-title">Unmatched Positions</span>
              {filteredRuns.reduce((sum, r) => sum + r.position_mismatches, 0) > 0 && (
                <span
                  className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                  style={{ backgroundColor: "#fef2f2", color: "#dc2626" }}
                >
                  {filteredRuns.reduce((sum, r) => sum + r.position_mismatches, 0)}
                </span>
              )}
            </div>
            <div className="panel-body" style={{ padding: 0 }}>
              {filteredRuns.filter((r) => r.position_mismatches > 0).length === 0 ? (
                <div className="empty-state">
                  <p>No unmatched positions found.</p>
                </div>
              ) : (
                <table className="w-full">
                  <thead>
                    <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                      {["Run ID", "Symbol", "Type", "Expected", "Actual", "Diff"].map((h) => (
                        <th
                          key={h}
                          className="px-4 py-2.5 text-left text-xs font-medium whitespace-nowrap"
                          style={{ color: "#9ca3af" }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRuns
                      .filter((r) => r.position_mismatches > 0)
                      .flatMap((r) => {
                        const rows = [];
                        for (let i = 0; i < Math.min(r.position_mismatches, 3); i++) {
                          rows.push(
                            <tr
                              key={`${r.run_id}-${i}`}
                              style={{
                                borderBottom: "1px solid #f9fafb",
                                backgroundColor: "#fffbeb",
                              }}
                            >
                              <td className="px-4 py-2.5 text-xs font-mono" style={{ color: "#6b7280" }}>
                                <code style={{ fontSize: "0.6875rem" }}>{r.run_id.slice(0, 8)}…</code>
                              </td>
                              <td className="px-4 py-2.5 text-xs font-semibold" style={{ color: "#111827" }}>
                                —
                              </td>
                              <td className="px-4 py-2.5">
                                <span
                                  className="text-xs px-1.5 py-0.5 rounded"
                                  style={{ backgroundColor: "#f3f4f6", color: "#6b7280" }}
                                >
                                  position
                                </span>
                              </td>
                              <td className="px-4 py-2.5 text-xs tabular-nums" style={{ color: "#374151" }}>
                                —
                              </td>
                              <td className="px-4 py-2.5 text-xs tabular-nums" style={{ color: "#374151" }}>
                                —
                              </td>
                              <td className="px-4 py-2.5 text-xs tabular-nums font-semibold" style={{ color: "#dc2626" }}>
                                —{r.position_mismatches > 0 ? ` (${r.position_mismatches} total)` : ""}
                              </td>
                            </tr>,
                          );
                        }
                        return rows;
                      })}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>

        {/* Right column: locks + run detail */}
        <div
          className="split-sidebar split-sidebar--narrow"
          style={{ width: 280, flexShrink: 0 }}
        >
          {/* Locks card panel */}
          <div className="card-panel">
            <div className="card-panel-header">
              <span className="card-panel-title">Blocking Locks</span>
              <span
                className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                style={{
                  backgroundColor: activeLocks.length > 0 ? "#fef2f2" : "#f3f4f6",
                  color: activeLocks.length > 0 ? "#dc2626" : "#6b7280",
                }}
              >
                {activeLocks.length} active
              </span>
            </div>
            <div className="panel-body" style={{ padding: 0 }}>
              {locks.length === 0 ? (
                <div className="empty-state">
                  <p>No blocking locks found.</p>
                </div>
              ) : (
                <div className="flex flex-col gap-0 divide-y" style={{ borderColor: "#f3f4f6" }}>
                  {locks.map((lock) => (
                    <div key={lock.lock_id} className="px-4 py-3">
                      <div className="flex items-center justify-between mb-1.5">
                        <span
                          className="text-xs font-semibold font-mono"
                          style={{ color: "#111827" }}
                        >
                          {lock.symbol}
                        </span>
                        <span
                          className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                          style={
                            lock.is_expired
                              ? { backgroundColor: "#f3f4f6", color: "#6b7280" }
                              : { backgroundColor: "#fef2f2", color: "#dc2626" }
                          }
                        >
                          {lock.is_expired ? "expired" : "active"}
                        </span>
                      </div>
                      <p
                        className="text-xs leading-relaxed mb-2"
                        style={{ color: "#6b7280" }}
                      >
                        {lock.lock_type} — {lock.strategy_code}
                      </p>
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center justify-between">
                          <span className="text-[10px]" style={{ color: "#9ca3af" }}>
                            Acquired
                          </span>
                          <span className="text-[10px] font-mono" style={{ color: "#374151" }}>
                            {new Date(lock.acquired_at).toLocaleTimeString()}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-[10px]" style={{ color: "#9ca3af" }}>
                            Expires
                          </span>
                          <span className="text-[10px] font-mono" style={{ color: "#374151" }}>
                            {lock.expires_at
                              ? new Date(lock.expires_at).toLocaleTimeString()
                              : "—"}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Run Detail card (conditional) */}
          {selectedRun && (
            <div className="card-panel" style={{ marginTop: "1rem" }}>
              <div className="card-panel-header">
                <span className="card-panel-title">Run Detail</span>
                <button
                  onClick={() => setSelectedRun(null)}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: "var(--text-muted)",
                    padding: 0,
                  }}
                >
                  <X size={13} />
                </button>
              </div>
              <div className="panel-body">
                <DetailRow label="Run ID" value={selectedRun.run_id} />
                <DetailRow label="Status" value={selectedRun.status} />
                <DetailRow label="Started" value={new Date(selectedRun.started_at).toLocaleString()} />
                <DetailRow label="Completed" value={selectedRun.completed_at ? new Date(selectedRun.completed_at).toLocaleString() : "—"} />
                <DetailRow
                  label="Order Mismatches"
                  value={String(selectedRun.order_mismatches)}
                  valueColor={
                    selectedRun.order_mismatches > 0 ? "var(--status-error)" : undefined
                  }
                />
                <DetailRow
                  label="Position Mismatches"
                  value={String(selectedRun.position_mismatches)}
                  valueColor={
                    selectedRun.position_mismatches > 0 ? "var(--status-error)" : undefined
                  }
                />
              </div>

              {/* Status footer */}
              {selectedRun.status === "completed" &&
                selectedRun.order_mismatches === 0 &&
                selectedRun.position_mismatches === 0 && (
                  <div className="status-footer status-footer--success">
                    <CheckCircle size={12} color="#16a34a" />
                    <span className="status-footer-text" style={{ color: "#16a34a" }}>
                      All positions matched successfully.
                    </span>
                  </div>
                )}
              {(selectedRun.order_mismatches > 0 ||
                selectedRun.position_mismatches > 0) && (
                <div className="status-footer status-footer--warn">
                  <AlertTriangle size={12} color="#d97706" />
                  <span className="status-footer-text" style={{ color: "#d97706" }}>
                    Mismatches require review.
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
