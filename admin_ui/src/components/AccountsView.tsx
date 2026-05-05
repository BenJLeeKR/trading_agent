import { useEffect, useMemo, useState } from "react";
import type { AccountSummary, OrderSummary, PositionSnapshotView, CashBalanceSnapshotView } from "../types/api";
import { getAccounts, getOrders, getPositions, getCashBalance } from "../api/client";
import { DataTable } from "./common/DataTable";
import { Panel } from "./common/Panel";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import type { Column } from "./common/DataTable";
import { Lock, Wallet, TrendingUp, TrendingDown, CheckCircle, Search, X } from "lucide-react";

/* ───────────────────────────────────────────
 * Helpers
 * ─────────────────────────────────────────── */
function formatCurrency(val: string | number | undefined | null): string {
  if (val == null) return "—";
  const n = typeof val === "string" ? Number.parseFloat(val) : val;
  if (Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

function formatQty(val: string | number | undefined | null): string {
  if (val == null) return "—";
  const n = typeof val === "string" ? Number.parseFloat(val) : val;
  if (Number.isNaN(n)) return "—";
  return n.toLocaleString();
}

function sideClass(side: string): string {
  return side.toLowerCase() === "long" ? "side-long" : "side-short";
}

/* ───────────────────────────────────────────
 * AccountStatusBadge — pill badge with dot
 * ─────────────────────────────────────────── */
function AccountStatusBadge({ status }: { status: string }) {
  const variant =
    status === "active" ? "success" :
    status === "locked" ? "error" :
    status === "pending" ? "warning" :
    "info";
  return (
    <span className={`status-badge status-badge--${variant}`}>
      <span className="status-badge-dot" />
      {status.toUpperCase()}
    </span>
  );
}

/* ───────────────────────────────────────────
 * SummaryCard — icon + value + label + change
 * ─────────────────────────────────────────── */
function SummaryCard({
  icon: Icon,
  iconBg,
  iconColor,
  label,
  value,
  change,
  changeUp,
}: {
  icon: React.ElementType;
  iconBg: string;
  iconColor: string;
  label: string;
  value: string;
  change?: string;
  changeUp?: boolean;
}) {
  return (
    <div className="summary-card">
      <div className="icon-row">
        <div className="icon" style={{ background: iconBg, color: iconColor }}>
          <Icon size={16} />
        </div>
      </div>
      <h3>{value}</h3>
      <p className="summary-card-label">{label}</p>
      {change && (
        <p className={`change${changeUp !== undefined ? (changeUp ? " change--up" : " change--down") : " change--neutral"}`}>
          {changeUp !== undefined ? (changeUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />) : null}
          {change}
        </p>
      )}
    </div>
  );
}

/* ───────────────────────────────────────────
 * AccountsView
 * ─────────────────────────────────────────── */
export default function AccountsView() {
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);
  const [positions, setPositions] = useState<PositionSnapshotView[]>([]);
  const [cashBalance, setCashBalance] = useState<CashBalanceSnapshotView | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Filter state
  const [searchText, setSearchText] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");

  // Phase 1: get orders to obtain a client_id (temporary heuristic),
  // then Phase 2: fetch accounts scoped to that client.
  useEffect(() => {
    setLoading(true);
    setError(null);
    getOrders()
      .then((orders: OrderSummary[]) => {
        if (orders.length === 0) {
          setAccounts([]);
          return;
        }
        const clientId = orders[0].client_id;
        return getAccounts(clientId);
      })
      .then((maybeAccounts: AccountSummary[] | undefined) => {
        if (maybeAccounts !== undefined) {
          setAccounts(maybeAccounts);
        }
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Failed to load accounts";
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedAccount) {
      setPositions([]);
      setCashBalance(null);
      return;
    }
    setDetailLoading(true);
    Promise.all([getPositions(selectedAccount), getCashBalance(selectedAccount)])
      .then(([p, c]) => {
        setPositions(p);
        setCashBalance(c);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Failed to load account detail";
        setError(msg);
      })
      .finally(() => setDetailLoading(false));
  }, [selectedAccount]);

  const filteredAccounts = useMemo(() => {
    return accounts.filter((a) => {
      const matchType = typeFilter === "all" || a.account_type === typeFilter;
      const matchSearch =
          !searchText ||
          a.account_code.toLowerCase().includes(searchText.toLowerCase()) ||
          a.client_code.toLowerCase().includes(searchText.toLowerCase());
      return matchType && matchSearch;
    });
  }, [accounts, searchText, typeFilter]);

  // If filtered list no longer contains selected account, reset selection
  const safeSelectedAccount = useMemo(() => {
    if (!selectedAccount) return null;
    return filteredAccounts.some((a) => a.account_id === selectedAccount)
      ? selectedAccount
      : null;
  }, [selectedAccount, filteredAccounts]);

  // Compute derived values
  const totalPnl = useMemo(() => {
    return positions.reduce((sum, p) => sum + (Number.parseFloat(p.pnl) || 0), 0);
  }, [positions]);

  const totalValue = useMemo(() => {
    const posValue = positions.reduce((sum, p) => sum + (Number.parseFloat(p.quantity) || 0) * (Number.parseFloat(p.current_price) || 0), 0);
    const cash = Number.parseFloat(cashBalance?.total_amount ?? "0") || 0;
    return posValue + cash;
  }, [positions, cashBalance]);

  const selectedAccountDetail = safeSelectedAccount
    ? accounts.find((a) => a.account_id === safeSelectedAccount)
    : null;

  const positionColumns: Column<PositionSnapshotView>[] = [
    { key: "symbol", label: "Symbol" },
    {
      key: "side",
      label: "Side",
      render: (r) => (
        <span className={sideClass(r.side)}>{r.side.toUpperCase()}</span>
      ),
    },
    { key: "quantity", label: "Qty", render: (r) => formatQty(r.quantity) },
    { key: "avg_price", label: "Avg Price", render: (r) => formatCurrency(r.avg_price) },
    { key: "current_price", label: "Current Price", render: (r) => formatCurrency(r.current_price) },
    {
      key: "pnl",
      label: "PnL",
      render: (r) => {
        const pnl = Number.parseFloat(r.pnl) || 0;
        return (
          <span style={{ color: pnl >= 0 ? "var(--color-success, #10b981)" : "var(--color-error, #ef4444)", fontWeight: 600 }}>
            {pnl >= 0 ? "+" : ""}{formatCurrency(pnl)}
          </span>
        );
      },
    },
    { key: "snapshot_time", label: "Snapshot" },
  ];

  const typeOptions = [
    { label: "All", value: "all" },
    { label: "Cash", value: "cash" },
    { label: "Margin", value: "margin" },
  ];

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  return (
    <section>
      <div className="page-header">
        <h2>Accounts & Positions</h2>
        <p>Select an account to view its positions and cash balance.</p>
      </div>

      {/* ── Filter bar ── */}
      <div className="filter-bar">
        <div className="input-wrap">
          <Search size={14} className="input-wrap-icon" />
          <input
            type="search"
            placeholder="Search by code or alias..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            aria-label="Search accounts"
          />
          {searchText && (
            <button className="input-wrap-clear" onClick={() => setSearchText("")} aria-label="Clear search">
              <X size={14} />
            </button>
          )}
        </div>

        <div className="filter-group" role="group" aria-label="Type">
          {typeOptions.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`pill-btn${typeFilter === opt.value ? " pill-btn--active" : ""}`}
              onClick={() => setTypeFilter(opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Split layout ── */}
      <div className="split-layout">
        {/* Left: account card list (248px) */}
        <div className="split-sidebar--card-list">
          {filteredAccounts.length === 0 ? (
            <p className="text-muted" style={{ padding: "1rem" }}>No accounts found.</p>
          ) : (
            filteredAccounts.map((acc) => {
              const isSelected = acc.account_id === safeSelectedAccount;
              return (
                <button
                  key={acc.account_id}
                  className={`account-card${isSelected ? " account-card--selected" : ""}`}
                  onClick={() => setSelectedAccount(acc.account_id)}
                >
                  <div className="flex items-start justify-between mb-1">
                    <div>
                      <p className="account-card-name">{acc.account_code}</p>
                      <p className="account-card-id">{acc.account_id.slice(0, 12)}…</p>
                    </div>
                    <AccountStatusBadge status={acc.status} />
                  </div>

                  <div className="flex items-center justify-between mt-2">
                    <div>
                      <p className="account-card-label">Total Value</p>
                      <p className="account-card-value">—</p>
                    </div>
                    <div className="text-right">
                      <p className="account-card-label">Status</p>
                      <p className="account-card-value">{acc.status}</p>
                    </div>
                  </div>

                  <p className="account-card-broker">{acc.account_type} · {acc.currency}</p>
                </button>
              );
            })
          )}
        </div>

        {/* Right: detail */}
        <div className="split-main">
          {safeSelectedAccount && selectedAccountDetail ? (
            <>
              {/* Locked warning */}
              {selectedAccountDetail.status === "locked" && (
                <div className="status-banner status-banner--error">
                  <Lock size={16} />
                  <strong>Account Locked</strong>
                  <span>This account is currently locked. Trading and modifications are restricted.</span>
                </div>
              )}

              {detailLoading ? (
                <LoadingSpinner text="Loading account detail..." />
              ) : (
                <>
                  {/* Summary cards */}
                  <div className="summary-card-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
                    <SummaryCard
                      icon={Wallet}
                      iconBg="#eef2ff"
                      iconColor="#6366f1"
                      label="Total Value"
                      value={formatCurrency(totalValue)}
                    />
                    <SummaryCard
                      icon={Wallet}
                      iconBg="#ecfdf5"
                      iconColor="#10b981"
                      label="Cash Balance"
                      value={cashBalance ? formatCurrency(cashBalance.total_amount) : "—"}
                    />
                    <SummaryCard
                      icon={totalPnl >= 0 ? TrendingUp : TrendingDown}
                      iconBg={totalPnl >= 0 ? "#ecfdf5" : "#fef2f2"}
                      iconColor={totalPnl >= 0 ? "#10b981" : "#ef4444"}
                      label="Day P&L"
                      value={totalPnl >= 0 ? `+${formatCurrency(totalPnl)}` : formatCurrency(totalPnl)}
                      change={totalPnl >= 0 ? "Gain" : "Loss"}
                      changeUp={totalPnl >= 0}
                    />
                  </div>

                  {/* Cash balance detail */}
                  {cashBalance && (
                    <div className="card-panel" style={{ marginTop: "0.5rem" }}>
                      <div className="card-panel-header">
                        <span className="card-panel-title">Cash Balance Detail</span>
                      </div>
                      <div style={{ padding: "0.75rem 1rem", display: "flex", gap: "2rem", fontSize: "0.8125rem" }}>
                        <div>
                          <span className="text-muted">Available: </span>
                          <span className="font-semibold">{formatCurrency(cashBalance.available_amount)}</span>
                        </div>
                        <div>
                          <span className="text-muted">Currency: </span>
                          <span className="font-semibold">{cashBalance.currency}</span>
                        </div>
                        <div>
                          <span className="text-muted">Snapshot: </span>
                          <span className="font-semibold">{cashBalance.snapshot_time}</span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Positions table */}
                  <div className="card-panel" style={{ marginTop: "0.5rem" }}>
                    <div className="card-panel-header">
                      <span className="card-panel-title">Positions</span>
                      {positions.length > 0 && (
                        <span className="card-panel-count">{positions.length}</span>
                      )}
                    </div>
                    <DataTable
                      columns={positionColumns}
                      data={positions}
                      keyField="position_snapshot_id"
                      emptyMessage="No positions for this account."
                      compact
                    />
                  </div>
                </>
              )}
            </>
          ) : (
            <div className="split-main-placeholder">
              <Wallet size={32} />
              <p>Select an account from the left panel to view details.</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
