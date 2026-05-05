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
import {
  Activity,
  ClipboardList,
  Lock,
  RefreshCcw,
  AlertTriangle,
  CheckCircle,
  TrendingUp,
  TrendingDown,
  XCircle,
} from "lucide-react";

/* ── Summary Card with template icon pattern ── */
interface CardData {
  label: string;
  value: string | number;
  variant?: "ok" | "warn" | "error";
  to?: string;
  icon: React.ElementType;
  iconBg: string;
  iconColor: string;
  change?: string;
  changeUp?: boolean | null;
  alert?: boolean;
  children?: ReactNode;
}

function SummaryCard({
  label,
  value,
  variant = "ok",
  to,
  icon: Icon,
  iconBg,
  iconColor,
  change,
  changeUp,
  alert,
  children,
}: CardData) {
  const variantClass =
    variant === "ok"
      ? "summary-card--ok"
      : variant === "warn"
        ? "summary-card--warn"
        : "summary-card--error";

  const changeClass =
    changeUp === true
      ? "summary-card-change--up"
      : changeUp === false
        ? "summary-card-change--down"
        : "summary-card-change--neutral";

  const content = (
    <>
      <div className="summary-card-icon-row">
        <div
          className="summary-card-icon"
          style={{ backgroundColor: iconBg }}
        >
          <Icon size={16} style={{ color: iconColor }} />
        </div>
        {alert && (
          <span className="summary-card-alert-badge">Needs attention</span>
        )}
      </div>
      <div>
        <h3>{value}</h3>
        <small>{label}</small>
      </div>
      {(change || children) && (
        <div className="summary-card-change">
          {changeUp === true && <TrendingUp size={11} />}
          {changeUp === false && <TrendingDown size={11} />}
          {change && (
            <span className={changeClass}>
              {change}
              {changeUp !== null && (
                <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>
                  {" "}
                  vs last 7d
                </span>
              )}
            </span>
          )}
          {children && <div className="summary-card-metrics">{children}</div>}
        </div>
      )}
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

      // Phase 3: fetch remaining data in parallel
      const [h, r, l] = await Promise.all([
        getHealth(),
        accountId
          ? getReconciliationRuns(accountId)
          : Promise.resolve<ReconciliationRunSummary[]>([]),
        accountId
          ? getReconciliationLocks(accountId)
          : Promise.resolve<BlockingLockStatus[]>([]),
      ]);
      setHealth(h);
      setReconRuns(r);
      setLocks(l);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Failed to load dashboard";
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

  if (error)
    return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  const serverStatusVariant =
    health?.status === "ok"
      ? "ok"
      : health?.status === "degraded"
        ? "warn"
        : "error";

  const pendingOrders = orders.filter((o) => o.status === "pending").length;
  const filledOrders = orders.filter((o) => o.status === "filled").length;

  const cards: CardData[] = [
    {
      label: "Server Status",
      value: health?.status ?? "unknown",
      variant: serverStatusVariant,
      icon: Activity,
      iconBg: "#eff6ff",
      iconColor: "#3b82f6",
      change:
        health?.status === "ok"
          ? "All systems operational"
          : health?.status === "degraded"
            ? "Performance degraded"
            : "System error",
      changeUp:
        health?.status === "ok"
          ? true
          : health?.status === "degraded"
            ? false
            : null,
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
      icon: ClipboardList,
      iconBg: "#f5f3ff",
      iconColor: "#8b5cf6",
      change: `${pendingOrders} pending, ${filledOrders} filled`,
      changeUp: null,
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
      icon: Lock,
      iconBg: activeLocks.length > 0 ? "#fffbeb" : "#f0fdf4",
      iconColor: activeLocks.length > 0 ? "#f59e0b" : "#10b981",
      change:
        activeLocks.length > 0
          ? `${activeLocks.length} lock${activeLocks.length > 1 ? "s" : ""} active`
          : "No locks",
      changeUp: activeLocks.length > 0 ? false : true,
      alert: activeLocks.length > 0,
    },
    {
      label: "Incomplete Runs",
      value: incompleteRuns.length,
      variant: incompleteRuns.length > 0 ? "warn" : "ok",
      to: incompleteRuns.length > 0 ? "/reconciliation" : undefined,
      icon: RefreshCcw,
      iconBg: incompleteRuns.length > 0 ? "#fef2f2" : "#f0fdf4",
      iconColor: incompleteRuns.length > 0 ? "#ef4444" : "#10b981",
      change:
        incompleteRuns.length > 0
          ? `${incompleteRuns.length} run${incompleteRuns.length > 1 ? "s" : ""} incomplete`
          : "All runs complete",
      changeUp: incompleteRuns.length > 0 ? false : true,
      alert: incompleteRuns.length > 0,
    },
  ];

  const dbVariant = health?.database === "connected" ? "ok" : "error";

  /* ── Alerts panel from template ── */
  const systemStatus = [
    { label: "Order Router", ok: true },
    {
      label: "Broker Feed",
      ok: health?.status !== "degraded" && health?.status !== "error",
    },
    {
      label: "Recon Engine",
      ok: incompleteRuns.length === 0,
    },
    { label: "Decision Engine", ok: true },
  ];

  const alertItems = [
    ...(activeLocks.length > 0
      ? [
          {
            icon: Lock,
            color: "#dc2626",
            bg: "#fef2f2",
            border: "#fca5a5",
            title: "Active Lock",
            desc: `${activeLocks.length} account${activeLocks.length > 1 ? "s are" : " is"} locked during reconciliation.`,
            time: "Now",
          },
        ]
      : []),
    ...(incompleteRuns.length > 0
      ? [
          {
            icon: RefreshCcw,
            color: "#d97706",
            bg: "#fffbeb",
            border: "#fcd34d",
            title: "Reconciliation Required",
            desc: `${incompleteRuns.length} run${incompleteRuns.length > 1 ? "s have" : " has"} unmatched positions.`,
            time: "Now",
          },
        ]
      : []),
    ...(health?.status && health.status !== "ok"
      ? [
          {
            icon: AlertTriangle,
            color: "#d97706",
            bg: "#fffbeb",
            border: "#fcd34d",
            title: "Degraded Health",
            desc:
              health.status === "degraded"
                ? "Broker feed latency exceeded threshold."
                : "System is in error state.",
            time: "Now",
          },
        ]
      : []),
  ];

  return (
    <section>
      <div className="page-header">
        <h2>Dashboard</h2>
        <p>Trading overview & management</p>
      </div>

      {/* Warning: Health degraded */}
      {health?.status && health.status !== "ok" && (
        <div className="warning-banner warning-banner--error">
          <div className="warning-banner-content">
            {health.status === "error" ? <XCircle size={16} /> : <AlertTriangle size={16} />}
            <div>
              <span className="warning-banner-strong">
                System Status: {health.status.toUpperCase()}
              </span>
              <br />
              <span>
                Database:{" "}
                {health.database === "connected" ? "Connected" : "Disconnected"}
                {health.database !== "connected" &&
                  " — Some features may be unavailable."}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Summary cards */}
      <div className="summary-cards-grid">
        {cards.map((c) => (
          <SummaryCard
            key={c.label}
            label={c.label}
            value={c.value}
            variant={c.variant}
            to={c.to}
            icon={c.icon}
            iconBg={c.iconBg}
            iconColor={c.iconColor}
            change={c.change}
            changeUp={c.changeUp}
            alert={c.alert}
          >
            {c.children}
          </SummaryCard>
        ))}
      </div>

      {/* Dashboard body: main content + alerts sidebar */}
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
                className="health-dot"
                style={{
                  backgroundColor:
                    dbVariant === "ok"
                      ? "var(--status-success)"
                      : "var(--status-error)",
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
                  {
                    key: "status",
                    label: "Status",
                    render: (o) => <StatusBadge status={o.status} />,
                  },
                ]}
                data={orders.slice(0, 5)}
                keyField="order_request_id"
                onRowClick={(o) => navigate(`/orders/${o.order_request_id}`)}
                compact
              />
            )}
            {orders.length > 5 && (
              <div className="table-footer">
                <small className="text-muted">
                  Showing 5 of {orders.length} orders.
                </small>
              </div>
            )}
          </Panel>
        </div>

        {/* Alerts sidebar (template pattern) */}
        <div className="alerts-sidebar">
          {/* System Health */}
          <div className="alerts-panel">
            <p className="alerts-panel-title">System Health</p>
            <div>
              {systemStatus.map((s) => (
                <div key={s.label} className="system-status-item">
                  <span className="system-status-label">{s.label}</span>
                  <div className={`system-status-value system-status-value--${s.ok ? "ok" : "degraded"}`}>
                    {s.ok ? (
                      <CheckCircle size={12} />
                    ) : (
                      <AlertTriangle size={12} />
                    )}
                    <span>{s.ok ? "Operational" : "Degraded"}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Active Alerts */}
          <div className="alerts-panel">
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: "0.75rem",
              }}
            >
              <p className="alerts-panel-title" style={{ marginBottom: 0 }}>
                Active Alerts
              </p>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.25rem",
                }}
              >
                <Activity size={11} color="#ef4444" />
                <span
                  style={{
                    fontSize: "0.6rem",
                    fontWeight: 700,
                    color: "#ef4444",
                  }}
                >
                  {alertItems.length}
                </span>
              </div>
            </div>
            <div>
              {alertItems.length === 0 ? (
                <p
                  style={{
                    fontSize: "0.7rem",
                    color: "var(--text-muted)",
                    textAlign: "center",
                    padding: "0.5rem 0",
                  }}
                >
                  No active alerts
                </p>
              ) : (
                alertItems.map((a) => {
                  const Icon = a.icon;
                  return (
                    <div
                      key={a.title}
                      className="alert-item"
                      style={{
                        backgroundColor: a.bg,
                        borderColor: a.border,
                      }}
                    >
                      <Icon
                        size={14}
                        className="alert-item-icon"
                        style={{ color: a.color }}
                      />
                      <div style={{ minWidth: 0 }}>
                        <p
                          className="alert-item-title"
                          style={{ color: a.color }}
                        >
                          {a.title}
                        </p>
                        <p className="alert-item-desc">{a.desc}</p>
                        <p className="alert-item-time">{a.time}</p>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
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
