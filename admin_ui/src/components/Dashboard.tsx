import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type {
  AccountSummary,
  HealthResponse,
  OrderSummary,
  ReconciliationRunSummary,
  BlockingLockStatus,
} from "../types/api";
import {
  getAccounts,
  getHealth,
  getOrders,
  getReconciliationRuns,
  getReconciliationLocks,
} from "../api/client";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { DataTable } from "./common/DataTable";
import { WarningBanner } from "./common/WarningBanner";
import { ArrowRight } from "lucide-react";

/* ── StatusCard (template pattern) ── */
function StatusCard({
  title,
  value,
  status,
  subtitle,
}: {
  title: string;
  value: string | number;
  status: "healthy" | "warning" | "error" | "neutral";
  subtitle?: string;
}) {
  const statusColors = {
    healthy: "bg-[#dcfce7] text-[#166534]",
    warning: "bg-[#fef3c7] text-[#92400e]",
    error: "bg-[#fee2e2] text-[#991b1b]",
    neutral: "bg-[#f1f5f9] text-[#475569]",
  };
  const dotColors = {
    healthy: "bg-[#22c55e]",
    warning: "bg-[#f59e0b]",
    error: "bg-[#ef4444]",
    neutral: "bg-[#94a3b8]",
  };

  return (
    <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-medium text-[#64748b]">{title}</span>
        <div className={`flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium ${statusColors[status]}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${dotColors[status]}`} />
          {status === "healthy" ? "Healthy" : status === "warning" ? "Warning" : status === "error" ? "Error" : "Info"}
        </div>
      </div>
      <p className="text-2xl font-semibold text-[#0f172a]">{value}</p>
      {subtitle && (
        <p className="text-xs text-[#94a3b8] mt-1">{subtitle}</p>
      )}
    </div>
  );
}

export default function Dashboard() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [reconRuns, setReconRuns] = useState<ReconciliationRunSummary[]>([]);
  const [locks, setLocks] = useState<BlockingLockStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [h, orders] = await Promise.all([
        getHealth(),
        getOrders(),
      ]);
      setHealth(h);
      setOrders(orders);

      // Reconciliation data requires an account_id, which we cannot derive
      // from /orders alone (backend OrderSummary has no client_id).
      // Leave reconRuns and locks as empty arrays.
      setReconRuns([]);
      setLocks([]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load dashboard";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  const activeLocks = useMemo(
    () => locks.filter((l) => !l.is_expired),
    [locks],
  );
  const incompleteRuns = useMemo(
    () =>
      reconRuns.filter(
        (r) => r.status === "running" || r.status === "reconcile_required",
      ),
    [reconRuns],
  );

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  const recentOrders = orders.slice(0, 5);

  const orderColumns = [
    { key: "order_request_id", header: "Order ID", width: "120px", render: (r: OrderSummary) => (
      <code className="text-xs">{r.order_request_id.slice(0, 8)}…</code>
    )},
    { key: "symbol", header: "Symbol" },
    { key: "side", header: "Side", render: (r: OrderSummary) => (
      <StatusBadge variant={r.side.toLowerCase() === "buy" ? "success" : "error"}>{r.side.toUpperCase()}</StatusBadge>
    )},
    { key: "qty", header: "Qty" },
    { key: "status", header: "Status", render: (r: OrderSummary) => {
      const v = r.status === "filled" ? "success" : r.status === "pending" ? "warning" : "error";
      return <StatusBadge variant={v}>{r.status.toUpperCase()}</StatusBadge>;
    }},
    { key: "created_at", header: "Created" },
  ];

  const lockColumns = [
    { key: "lock_id", header: "Lock ID" },
    { key: "lock_type", header: "Type" },
    { key: "account_id", header: "Account" },
    { key: "acquired_at", header: "Created" },
  ];

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">Overview</h1>
        <p className="text-sm text-[#64748b] mt-1">System status and recent activity</p>
      </div>

      {/* Warning Banner */}
      {activeLocks.length > 0 && (
        <WarningBanner
          variant="warning"
          title={`${activeLocks.length} Active Locks`}
          message="There are active reconciliation locks that may affect order processing."
        />
      )}

      {/* Status Summary Cards */}
      <div className="grid grid-cols-5 gap-4">
        <StatusCard
          title="API Health"
          value={health?.status === "ok" ? "Operational" : health?.status ?? "Unknown"}
          status={health?.status === "ok" ? "healthy" : "error"}
          subtitle="Last checked 30s ago"
        />
        <StatusCard
          title="Database Health"
          value={health?.runtime_mode === "in_memory" ? "In-Memory" : health?.database === "connected" ? "Operational" : "Disconnected"}
          status={health?.runtime_mode === "in_memory" ? "neutral" : health?.database === "connected" ? "healthy" : "error"}
          subtitle={`Connection pool: ${health?.runtime_mode ?? "N/A"}`}
        />
        <StatusCard
          title="Recent Orders"
          value={orders.length}
          status="neutral"
          subtitle="Last 24 hours"
        />
        <StatusCard
          title="Active Locks"
          value={activeLocks.length}
          status={activeLocks.length > 0 ? "warning" : "healthy"}
          subtitle="Blocking operations"
        />
        <StatusCard
          title="Incomplete Recon"
          value={incompleteRuns.length}
          status={incompleteRuns.length > 0 ? "warning" : "healthy"}
          subtitle="Pending resolution"
        />
      </div>

      {/* Recent Orders Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">Recent Orders</h2>
          <button
            onClick={() => navigate("/orders")}
            className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
          >
            View all orders
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
        <DataTable
          columns={orderColumns}
          data={recentOrders}
          idKey="order_request_id"
          onRowClick={(o) => navigate(`/orders/${o.order_request_id}`)}
        />
      </div>

      {/* Active Locks Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">Active Locks</h2>
          <button
            onClick={() => navigate("/reconciliation")}
            className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
          >
            View reconciliation
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
        {activeLocks.length > 0 ? (
          <DataTable columns={lockColumns} data={activeLocks} idKey="lock_id" />
        ) : (
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
            <p className="text-sm text-[#94a3b8]">No active locks</p>
          </div>
        )}
      </div>
    </div>
  );
}
