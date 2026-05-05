import { useEffect, useMemo, useState } from "react";
import type { ReconciliationRunSummary, BlockingLockStatus, AccountSummary, OrderSummary } from "../types/api";
import { getAccounts, getOrders, getReconciliationRuns, getReconciliationLocks } from "../api/client";
import { DataTable } from "./common/DataTable";
import { Panel } from "./common/Panel";
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

/* ───────────────────────────────────────────
 * FilterGroup — single-select button group
 * ─────────────────────────────────────────── */
function FilterGroup({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { label: string; value: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="filter-group" role="group" aria-label={label}>
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`filter-group-btn${value === opt.value ? " filter-group-btn--active" : ""}`}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function formatStatusLabel(status: string): string {
  if (status === "all") return "All";
  return status
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

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
        <div className="tab-content">
          <FilterGroup
            label="Status"
            options={RUN_STATUSES.map((s) => ({
              label: formatStatusLabel(s),
              value: s,
            }))}
            value={runStatusFilter}
            onChange={setRunStatusFilter}
          />
          <Panel title="Reconciliation Runs">
            <DataTable
              columns={runColumns}
              data={filteredRuns}
              keyField="run_id"
              emptyMessage="No reconciliation runs found."
              compact
            />
          </Panel>
        </div>
      )}

      {activeTab === "locks" && (
        <div className="tab-content">
          {activeLocks.length > 0 && (
            <div className="warning-banner warning-banner--error">
              <svg
                className="warning-banner-icon"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="12" r="10" />
                <line x1="15" y1="9" x2="9" y2="15" />
                <line x1="9" y1="9" x2="15" y2="15" />
              </svg>
              <div className="warning-banner-content">
                <span className="warning-banner-strong">
                  {activeLocks.length} Active Blocking Lock{activeLocks.length !== 1 ? "s" : ""}
                </span>
                <br />
                <span className="warning-banner-body">
                  These may block trading operations. Resolve locks before submitting new orders.
                </span>
              </div>
            </div>
          )}
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
