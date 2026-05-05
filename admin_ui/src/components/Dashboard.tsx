import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type {
  HealthResponse,
  OrderSummary,
  ReconciliationRunSummary,
  BlockingLockStatus,
} from "../types/api";
import {
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

function SummaryCard({ label, value, variant, to }: CardData) {
  const color =
    variant === "ok"
      ? "var(--pico-ins-color)"
      : variant === "warn"
        ? "var(--pico-warning)"
        : variant === "error"
          ? "var(--pico-del-color)"
          : "var(--pico-primary)";

  const content = (
    <>
      <h3 style={{ margin: 0, color }}>{value}</h3>
      <small style={{ color: "var(--pico-muted-color)" }}>{label}</small>
    </>
  );

  const style: React.CSSProperties = {
    textAlign: "center",
    padding: "1rem",
    borderTop: `3px solid ${color}`,
    cursor: to ? "pointer" : undefined,
    transition: "opacity 0.15s",
  };

  if (to) {
    return (
      <Link
        to={to}
        style={{ textDecoration: "none", color: "inherit" }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.opacity = "0.8";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.opacity = "1";
        }}
      >
        <article style={style}>{content}</article>
      </Link>
    );
  }

  return <article style={style}>{content}</article>;
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
      const [h, o, r, l] = await Promise.all([
        getHealth(),
        getOrders(),
        getReconciliationRuns(),
        getReconciliationLocks(),
      ]);
      setHealth(h);
      setOrders(o);
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
      <hgroup>
        <h2>Dashboard</h2>
        <p>Read-only overview of system status.</p>
      </hgroup>

      {/* Health status detail banner */}
      {health?.status && health.status !== "ok" && (
        <article
          style={{
            backgroundColor: "var(--pico-del-background)",
            color: "var(--pico-del-color)",
            padding: "0.5rem 1rem",
            marginBottom: "1rem",
            borderRadius: "4px",
            border: "1px solid var(--pico-del-color)",
          }}
        >
          <strong>⚠️ System Status: {health.status.toUpperCase()}</strong>
          <br />
          <span style={{ fontWeight: "normal" }}>
            Database: {health.database === "connected" ? "Connected" : "Disconnected"}
            {health.database !== "connected" && " — Some features may be unavailable."}
          </span>
        </article>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: "1rem",
          marginBottom: "2rem",
        }}
      >
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
                  dbVariant === "ok" ? "var(--pico-ins-color)" : "var(--pico-del-color)",
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
            <p style={{ color: "var(--pico-muted-color)" }}>No locks.</p>
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
                    style={{ cursor: "pointer" }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLElement).style.backgroundColor =
                        "var(--pico-primary-background)";
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLElement).style.backgroundColor =
                        "transparent";
                    }}
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
            <p style={{ color: "var(--pico-muted-color)" }}>No orders.</p>
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
                    style={{ cursor: "pointer" }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLElement).style.backgroundColor =
                        "var(--pico-primary-background)";
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLElement).style.backgroundColor =
                        "transparent";
                    }}
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

      <footer>
        <button className="outline" onClick={fetchAll}>
          🔄 Refresh
        </button>
      </footer>
    </section>
  );
}
