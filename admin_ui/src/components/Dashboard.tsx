import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
import { Panel } from "./common/Panel";
import { DataTable } from "./common/DataTable";

/* ── SVG Icons ── */
function AlertTriangleIcon() {
  return (
    <svg className="warning-banner-icon" viewBox="0 0 24 24">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}
function XCircleIcon() {
  return (
    <svg className="warning-banner-icon" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="10" />
      <line x1="15" y1="9" x2="9" y2="15" />
      <line x1="9" y1="9" x2="15" y2="15" />
    </svg>
  );
}

/* ── Summary Card with optional children (sub-metrics) ── */
interface CardData {
  label: string;
  value: string | number;
  variant?: "ok" | "warn" | "error";
  to?: string;
  children?: ReactNode;
}

function SummaryCard({ label, value, variant = "ok", to, children }: CardData) {
  const variantClass =
    variant === "ok"
      ? "summary-card--ok"
      : variant === "warn"
        ? "summary-card--warn"
        : "summary-card--error";

  const color =
    variant === "ok"
      ? "var(--status-success)"
      : variant === "warn"
        ? "var(--status-warning)"
        : "var(--status-error)";

  const content = (
    <>
      <h3 style={{ color }}>{value}</h3>
      <small>{label}</small>
      {children && <div className="summary-card-metrics">{children}</div>}
    </>
  );

  if (to) {
    return (
      <Link to={to} className={`summary-card ${variantClass}`}>
        {content}
      </Link>
    );
  }

  return <div className={`summary-card ${variantClass}`}>{content}</div>;
}

/* ── Metric Row ── */
function MetricRow({ label, value }: { label: string; value: string | number }) {
  return (
    <span className="metric-row">
      <span className="metric-row-label">{label}</span>
      <span className="metric-row-value">{value}</span>
    </span>
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
      // Phase 1: get orders to obtain a client_id (temporary heuristic)
      const orders = await getOrders();
      setOrders(orders);

      // Phase 2: use the first order's client_id to fetch accounts
      let accountId: string | undefined;
      if (orders.length > 0) {
        const clientId = orders[0].client_id;
        const accounts = await getAccounts(clientId);
        accountId = accounts.length > 0 ? accounts[0].account_id : undefined;
      }

      // Phase 3: fetch remaining data in parallel with account-scoped reconciliation calls
      const [h, r, l] = await Promise.all([
        getHealth(),
        accountId ? getReconciliationRuns(accountId) : Promise.resolve<ReconciliationRunSummary[]>([]),
        accountId ? getReconciliationLocks(accountId) : Promise.resolve<BlockingLockStatus[]>([]),
      ]);
      setHealth(h);
      setReconRuns(r);
      setLocks(l);
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
    () => reconRuns.filter(
      (r) => r.status === "running" || r.status === "reconcile_required"
    ),
    [reconRuns],
  );

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  if (loading) return <LoadingSpinner />;

  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  const serverStatusVariant =
    health?.status === "ok" ? "ok" : health?.status === "degraded" ? "warn" : "error";

  const pendingOrders = orders.filter((o) => o.status === "pending").length;
  const filledOrders = orders.filter((o) => o.status === "filled").length;

  const cards: CardData[] = [
    {
      label: "Server Status",
      value: health?.status ?? "unknown",
      variant: serverStatusVariant,
      children: health ? (
        <>
          <MetricRow label="db" value={health.database} />
          <MetricRow label="mode" value={health.mode} />
        </>
      ) : undefined,
    },
    {
      label: "Total Orders",
      value: orders.length,
      to: "/orders",
      children: (
        <>
          <MetricRow label="pending" value={pendingOrders} />
          <MetricRow label="filled" value={filledOrders} />
        </>
      ),
    },
    {
      label: "Active Locks",
      value: activeLocks.length,
      variant: activeLocks.length > 0 ? "warn" : "ok",
      to: activeLocks.length > 0 ? "/reconciliation" : undefined,
    },
    {
      label: "Incomplete Runs",
      value: incompleteRuns.length,
      variant: incompleteRuns.length > 0 ? "warn" : "ok",
      to: incompleteRuns.length > 0 ? "/reconciliation" : undefined,
    },
  ];

  const dbVariant = health?.database === "connected" ? "ok" : "error";

  return (
    <section>
      <div className="page-header">
        <h2>Dashboard</h2>
        <p>Read-only overview of system status.</p>
      </div>

      {/* Warning: Health degraded */}
      {health?.status && health.status !== "ok" && (
        <div className="warning-banner warning-banner--error">
          <div className="warning-banner-content">
            {health.status === "error" ? <XCircleIcon /> : <AlertTriangleIcon />}
            <div>
              <span className="warning-banner-strong">System Status: {health.status.toUpperCase()}</span>
              <br />
              <span>
                Database: {health.database === "connected" ? "Connected" : "Disconnected"}
                {health.database !== "connected" && " — Some features may be unavailable."}
              </span>
            </div>
          </div>
        </div>
      )}

      <div className="summary-cards-grid">
        {cards.map((c) => (
          <SummaryCard key={c.label} label={c.label} value={c.value} variant={c.variant} to={c.to}>
            {c.children}
          </SummaryCard>
        ))}
      </div>

      <div className="dashboard-body">
        {/* Main content left */}
        <div className="dashboard-main">
          {/* Database panel */}
          <Panel title="Database Status">
            <p>
              Mode: <code>{health?.mode ?? "—"}</code>
              <br />
              Status: <StatusBadge status={health?.database ?? "unknown"} />
            </p>
            <p>
              <span
                style={{
                  display: "inline-block",
                  width: "10px",
                  height: "10px",
                  borderRadius: "50%",
                  backgroundColor:
                    dbVariant === "ok" ? "var(--status-success)" : "var(--status-error)",
                  marginRight: "0.3rem",
                }}
              />
              {health?.database === "connected" ? "Connected" : "Disconnected"}
            </p>
          </Panel>

          {/* Recent Orders panel */}
          <Panel
            title="Recent Orders"
            headerRight={<small className="text-muted">Last 5</small>}
          >
            {orders.length === 0 ? (
              <p className="text-muted">No orders.</p>
            ) : (
              <DataTable
                columns={[
                  { key: "symbol", label: "Symbol" },
                  { key: "side", label: "Side" },
                  { key: "status", label: "Status", render: (o) => <StatusBadge status={o.status} /> },
                ]}
                data={orders.slice(0, 5)}
                keyField="order_request_id"
                onRowClick={(o) => navigate(`/orders/${o.order_request_id}`)}
                compact
              />
            )}
            {orders.length > 5 && (
              <div className="page-footer" style={{ marginTop: "0.5rem", paddingTop: "0.5rem" }}>
                <small className="text-muted">Showing 5 of {orders.length} orders.</small>
              </div>
            )}
          </Panel>
        </div>

        {/* Signals sidebar right */}
        <div className="signals-sidebar">
          {/* Active Locks Warnings */}
          <Panel title="Active Locks" noPadding>
            {activeLocks.length === 0 ? (
              <p className="text-muted" style={{ padding: "0.75rem" }}>No active locks.</p>
            ) : (
              <table className="signal-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Type</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {activeLocks.slice(0, 5).map((lk) => (
                    <tr
                      key={lk.lock_id}
                      onClick={() => navigate("/reconciliation")}
                      style={{ cursor: "pointer" }}
                    >
                      <td>{lk.symbol}</td>
                      <td>{lk.lock_type}</td>
                      <td><StatusBadge status="active" /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>

          {/* Incomplete Reconciliation Signals */}
          <Panel title="Incomplete Reconciliation" noPadding>
            {incompleteRuns.length === 0 ? (
              <p className="text-muted" style={{ padding: "0.75rem" }}>All runs complete.</p>
            ) : (
              <ul className="signal-list">
                {incompleteRuns.map((r) => (
                  <li key={r.run_id}>
                    <span className="signal-dot signal-dot--amber" />
                    <span className="signal-agent">{r.run_id.slice(0, 8)}</span>
                    <span className="signal-issue">{r.status}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>

      <div className="page-footer">
        <button className="outline" onClick={fetchAll}>
          🔄 Refresh
        </button>
      </div>
    </section>
  );
}
