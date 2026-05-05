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

interface CardData {
  label: string;
  value: string | number;
  variant?: "ok" | "warn" | "error";
  to?: string;
}

function SummaryCard({ label, value, variant = "ok", to }: CardData) {
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

  const cards: CardData[] = [
    {
      label: "Server Status",
      value: health?.status ?? "unknown",
      variant: serverStatusVariant,
    },
    {
      label: "Total Orders",
      value: orders.length,
      to: "/orders",
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

      {/* Health status detail banner — only shown when not ok */}
      {health?.status && health.status !== "ok" && (
        <div className="warning-banner warning-banner--error">
          <div>
            <span className="warning-banner-strong">⚠️ System Status: {health.status.toUpperCase()}</span>
            <br />
            <span>
              Database: {health.database === "connected" ? "Connected" : "Disconnected"}
              {health.database !== "connected" && " — Some features may be unavailable."}
            </span>
          </div>
        </div>
      )}

      <div className="summary-cards-grid">
        {cards.map((c) => (
          <SummaryCard key={c.label} label={c.label} value={c.value} variant={c.variant} to={c.to} />
        ))}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: "1rem",
        }}
      >
        <article>
          <header>
            <strong>Database</strong>
          </header>
          <p>
            Mode: <code>{health?.mode ?? "—"}</code>
            <br />
            Status: <StatusBadge status={health?.database ?? "unknown"} />
            <br />
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
        </article>

        <article>
          <header>
            <strong>Reconciliation Locks</strong>
          </header>
          {locks.length === 0 ? (
            <p className="text-muted">No locks.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {locks.slice(0, 5).map((lk) => (
                  <tr
                    key={lk.lock_id}
                    onClick={() => navigate("/reconciliation")}
                    className="cursor-pointer"
                  >
                    <td>{lk.symbol}</td>
                    <td>{lk.lock_type}</td>
                    <td>
                      <StatusBadge status={lk.is_expired ? "expired" : "active"} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {locks.length > 5 && (
            <footer>
              <small>Showing 5 of {locks.length} locks.</small>
            </footer>
          )}
        </article>

        <article>
          <header>
            <strong>Recent Orders</strong>
          </header>
          {orders.length === 0 ? (
            <p className="text-muted">No orders.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {orders.slice(0, 5).map((o) => (
                  <tr
                    key={o.order_request_id}
                    onClick={() => navigate(`/orders/${o.order_request_id}`)}
                    className="cursor-pointer"
                  >
                    <td>{o.symbol}</td>
                    <td>{o.side}</td>
                    <td>
                      <StatusBadge status={o.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {orders.length > 5 && (
            <footer>
              <small>Showing 5 of {orders.length} orders.</small>
            </footer>
          )}
        </article>
      </div>

      <div className="page-footer">
        <button className="outline" onClick={fetchAll}>
          🔄 Refresh
        </button>
      </div>
    </section>
  );
}
