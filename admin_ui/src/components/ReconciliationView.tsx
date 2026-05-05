import { useEffect, useMemo, useState } from "react";
import type { ReconciliationRunSummary, BlockingLockStatus } from "../types/api";
import { getReconciliationRuns, getReconciliationLocks } from "../api/client";
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
    Promise.all([getReconciliationRuns(), getReconciliationLocks()])
      .then(([r, l]) => {
        setRuns(r);
        setLocks(l);
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
      <hgroup>
        <h2>Reconciliation</h2>
        <p>Reconciliation runs and blocking locks.</p>
      </hgroup>

      <div role="tablist" style={{ marginBottom: "1rem" }}>
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
            <article
              style={{
                backgroundColor: "var(--pico-del-background)",
                color: "var(--pico-del-color)",
                padding: "0.75rem 1rem",
                marginBottom: "1rem",
                borderRadius: "4px",
                border: "2px solid var(--pico-del-color)",
                fontWeight: "bold",
              }}
            >
              🚫 <strong>{activeLocks.length} Active Blocking Lock{activeLocks.length !== 1 ? "s" : ""}</strong>
              <br />
              <span style={{ fontWeight: "normal" }}>
                These may block trading operations. Resolve locks before submitting new orders.
              </span>
            </article>
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
