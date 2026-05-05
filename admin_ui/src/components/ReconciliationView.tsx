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

type Tab = "runs" | "locks";

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
  const [activeTab, setActiveTab] = useState<Tab>("runs");
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
    { key: "started_at", label: "Started" },
    { key: "completed_at", label: "Completed" },
    {
      key: "status",
      label: "Status",
      render: (r) => <StatusBadge status={r.status} />,
    },
    { key: "order_mismatches", label: "Order Mismatches" },
    { key: "position_mismatches", label: "Position Mismatches" },
  ];

  const lockColumns: Column<BlockingLockStatus>[] = [
    { key: "symbol", label: "Symbol" },
    { key: "lock_type", label: "Type" },
    { key: "strategy_code", label: "Strategy" },
    {
      key: "is_expired",
      label: "Status",
      render: (r) => (
        <StatusBadge status={r.is_expired ? "expired" : "active"} />
      ),
    },
    { key: "acquired_at", label: "Acquired" },
    { key: "expires_at", label: "Expires" },
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

      {/* Tab bar */}
      <div className="tab-bar" role="tablist">
        <button
          role="tab"
          aria-selected={activeTab === "runs"}
          onClick={() => setActiveTab("runs")}
        >
          Runs ({runs.length})
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "locks"}
          onClick={() => setActiveTab("locks")}
        >
          Locks ({locks.length})
        </button>
      </div>

      {/* Runs tab */}
      {activeTab === "runs" && (
        <div className="tab-content">
          <div className="filter-bar">
            <div className="filter-group" role="group" aria-label="Status">
              {RUN_STATUSES.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`filter-group-btn${runStatusFilter === s ? " filter-group-btn--active" : ""}`}
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

          <div className="split-layout">
            <div className="split-main">
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
                  compact
                />
              </Panel>
            </div>

            {/* Right: run detail panel */}
            {selectedRun && (
              <div className="split-sidebar split-sidebar--narrow">
                <div className="card-panel">
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
                  <div style={{ padding: "0.75rem 1rem" }}>
                    <DetailRow
                      label="Run ID"
                      value={selectedRun.run_id}
                    />
                    <DetailRow
                      label="Status"
                      value={selectedRun.status}
                    />
                    <DetailRow
                      label="Started"
                      value={selectedRun.started_at}
                    />
                    <DetailRow
                      label="Completed"
                      value={selectedRun.completed_at ?? "—"}
                    />
                    <DetailRow
                      label="Order Mismatches"
                      value={String(selectedRun.order_mismatches)}
                      valueColor={
                        selectedRun.order_mismatches > 0
                          ? "var(--status-error)"
                          : undefined
                      }
                    />
                    <DetailRow
                      label="Position Mismatches"
                      value={String(selectedRun.position_mismatches)}
                      valueColor={
                        selectedRun.position_mismatches > 0
                          ? "var(--status-error)"
                          : undefined
                      }
                    />
                  </div>

                  {/* Status footer */}
                  {selectedRun.status === "completed" &&
                    selectedRun.order_mismatches === 0 &&
                    selectedRun.position_mismatches === 0 && (
                      <div
                        style={{
                          padding: "0.6rem 1rem",
                          borderTop: "1px solid var(--border-color)",
                          backgroundColor: "#f0fdf4",
                          display: "flex",
                          alignItems: "center",
                          gap: "0.4rem",
                        }}
                      >
                        <CheckCircle size={12} color="#16a34a" />
                        <span
                          style={{
                            fontSize: "0.7rem",
                            color: "#16a34a",
                            fontWeight: 500,
                          }}
                        >
                          All positions matched successfully.
                        </span>
                      </div>
                    )}
                  {(selectedRun.order_mismatches > 0 ||
                    selectedRun.position_mismatches > 0) && (
                      <div
                        style={{
                          padding: "0.6rem 1rem",
                          borderTop: "1px solid var(--border-color)",
                          backgroundColor: "#fffbeb",
                          display: "flex",
                          alignItems: "center",
                          gap: "0.4rem",
                        }}
                      >
                        <AlertTriangle size={12} color="#d97706" />
                        <span
                          style={{
                            fontSize: "0.7rem",
                            color: "#d97706",
                            fontWeight: 500,
                          }}
                        >
                          Mismatches require review.
                        </span>
                      </div>
                    )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Locks tab */}
      {activeTab === "locks" && (
        <div className="tab-content">
          <Panel title="Blocking Locks">
            <DataTable
              columns={lockColumns}
              data={locks}
              keyField="lock_id"
              emptyMessage="No blocking locks found."
              compact
            />
          </Panel>
        </div>
      )}
    </section>
  );
}
