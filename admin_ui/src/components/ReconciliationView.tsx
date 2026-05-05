import { useEffect, useMemo, useState } from "react";
import type { ReconciliationRunSummary, BlockingLockStatus, AccountSummary, OrderSummary } from "../types/api";
import { getAccounts, getOrders, getReconciliationRuns, getReconciliationLocks } from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import type { Column } from "./common/DataTable";

type Tab = "runs" | "locks";

const RUN_STATUSES = [
  "all",
  "completed",
  "running",
  "reconcile_required",
  "failed",
] as const;

export default function ReconciliationView() {
  const [activeTab, setActiveTab] = useState<Tab>("runs");
  const [runs, setRuns] = useState<ReconciliationRunSummary[]>([]);
  const [locks, setLocks] = useState<BlockingLockStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runStatusFilter, setRunStatusFilter] = useState("all");

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
        <p>Reconciliation runs and blocking locks.</p>
      </div>

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

      {activeTab === "runs" && (
        <>
          <div style={{ marginBottom: "0.75rem" }}>
            <select
              value={runStatusFilter}
              onChange={(e) => setRunStatusFilter(e.target.value)}
              aria-label="Filter runs by status"
              style={{ minWidth: "160px" }}
            >
              {RUN_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s === "all"
                    ? "All Statuses"
                    : s
                        .split("_")
                        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                        .join(" ")}
                </option>
              ))}
            </select>
          </div>
          <DataTable
            columns={runColumns}
            data={filteredRuns}
            keyField="run_id"
            emptyMessage="No reconciliation runs found."
          />
        </>
      )}

      {activeTab === "locks" && (
        <>
          {activeLocks.length > 0 && (
            <div className="warning-banner warning-banner--error">
              <div>
                <span className="warning-banner-strong">
                  🚫 {activeLocks.length} Active Blocking Lock{activeLocks.length !== 1 ? "s" : ""}
                </span>
                <br />
                <span style={{ fontWeight: "normal" }}>
                  These may block trading operations. Resolve locks before submitting new orders.
                </span>
              </div>
            </div>
          )}
          <DataTable
            columns={lockColumns}
            data={locks}
            keyField="lock_id"
            emptyMessage="No blocking locks found."
          />
        </>
      )}
    </section>
  );
}
