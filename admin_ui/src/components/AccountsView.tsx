import { useEffect, useMemo, useState } from "react";
import type {
  AccountSummary,
  ClientDetail,
  PositionSnapshotView,
  CashBalanceSnapshotView,
} from "../types/api";
import { getClients, getAccounts, getPositions, getCashBalance } from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { FilterBar } from "./common/FilterBar";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import type { Column } from "./common/DataTable";
import { Lock, Wallet, TrendingUp, TrendingDown, X, Users } from "lucide-react";

/* ───────────────────────────────────────────
 * Helpers
 * ─────────────────────────────────────────── */
function formatCurrency(val: number | null | undefined): string {
  if (val == null) return "—";
  if (Number.isNaN(val)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(val);
}

function formatQty(val: number | null | undefined): string {
  if (val == null) return "—";
  if (Number.isNaN(val)) return "—";
  return val.toLocaleString();
}

function truncateUuid(uuid: string): string {
  return uuid.length > 8 ? uuid.slice(0, 8) + "…" : uuid;
}

/* ───────────────────────────────────────────
 * AccountsView
 * ─────────────────────────────────────────── */
export default function AccountsView() {
  const [clients, setClients] = useState<ClientDetail[]>([]);
  const [selectedClient, setSelectedClient] = useState<ClientDetail | null>(null);
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);
  const [positions, setPositions] = useState<PositionSnapshotView[]>([]);
  const [cashBalance, setCashBalance] = useState<CashBalanceSnapshotView | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Filter state
  const [searchText, setSearchText] = useState("");
  const [envFilter, setEnvFilter] = useState("");

  // ── Fetch clients → accounts ───────────────────────────────────
  useEffect(() => {
    setLoading(true);
    setError(null);

    getClients()
      .then((allClients) => {
        setClients(allClients);
        if (allClients.length === 0) {
          setAccounts([]);
          setLoading(false);
          return;
        }
        // Auto-select first client
        const first = allClients[0];
        setSelectedClient(first);
        return getAccounts(first.client_id);
      })
      .then((accts) => {
        if (accts) setAccounts(accts);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Failed to load accounts";
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, []);

  // ── Fetch positions / cash balance on account selection ─────────
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

  // ── Derived data ────────────────────────────────────────────────
  const filteredAccounts = useMemo(() => {
    return accounts.filter((a) => {
      const matchEnv = !envFilter || a.environment === envFilter;
      const matchSearch =
        !searchText ||
        (a.account_masked ?? "").toLowerCase().includes(searchText.toLowerCase()) ||
        (a.account_alias ?? "").toLowerCase().includes(searchText.toLowerCase());
      return matchEnv && matchSearch;
    });
  }, [accounts, searchText, envFilter]);

  const safeSelectedAccount = useMemo(() => {
    if (!selectedAccount) return null;
    return filteredAccounts.some((a) => a.account_id === selectedAccount)
      ? selectedAccount
      : null;
  }, [selectedAccount, filteredAccounts]);

  const selectedAccountDetail = safeSelectedAccount
    ? accounts.find((a) => a.account_id === safeSelectedAccount)
    : null;

  // Summary cards derived values
  const totalPnl = useMemo(() => {
    return positions.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0);
  }, [positions]);

  const totalValue = useMemo(() => {
    const posValue = positions.reduce(
      (sum, p) => sum + p.quantity * p.market_price,
      0,
    );
    const cash = cashBalance?.settled_cash ?? 0;
    return posValue + cash;
  }, [positions, cashBalance]);

  // ── Column definitions ──────────────────────────────────────────
  const accountColumns: Column<AccountSummary>[] = [
    {
      key: "account_masked",
      header: "Account #",
      render: (r) => r.account_masked ?? "—",
    },
    {
      key: "account_alias",
      header: "Alias",
      render: (r) => r.account_alias ?? "—",
    },
    {
      key: "environment",
      header: "Env",
      render: (r) => (
        <StatusBadge variant={r.environment === "live" ? "warning" : "info"}>
          {r.environment.toUpperCase()}
        </StatusBadge>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (r) => {
        const variant =
          r.status === "active"
            ? "success"
            : r.status === "locked"
              ? "error"
              : r.status === "pending"
                ? "warning"
                : "info";
        return <StatusBadge variant={variant}>{r.status.toUpperCase()}</StatusBadge>;
      },
    },
  ];

  const positionColumns: Column<PositionSnapshotView>[] = [
    {
      key: "instrument_id",
      header: "Instrument",
      render: (r) => (
        <span title={r.instrument_id} className="text-xs font-mono">
          {truncateUuid(r.instrument_id)}
        </span>
      ),
    },
    { key: "quantity", header: "Qty", render: (r) => formatQty(r.quantity) },
    {
      key: "average_price",
      header: "Avg Cost",
      render: (r) => formatCurrency(r.average_price),
    },
    {
      key: "market_price",
      header: "Market Price",
      render: (r) => formatCurrency(r.market_price),
    },
    {
      key: "unrealized_pnl",
      header: "Unrealized P&L",
      render: (r) => {
        const pnl = r.unrealized_pnl ?? 0;
        return (
          <span
            className={`text-xs font-semibold ${pnl >= 0 ? "text-[#16a34a]" : "text-[#dc2626]"}`}
          >
            {pnl >= 0 ? "+" : ""}
            {formatCurrency(pnl)}
          </span>
        );
      },
    },
    { key: "snapshot_at", header: "Snapshot" },
  ];

  // ── Render ──────────────────────────────────────────────────────
  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0f172a]">Accounts</h1>
          <p className="text-sm text-[#64748b] mt-1">
            View account status, positions, and cash balances
          </p>
        </div>
        {/* Selected client indicator */}
        {selectedClient && (
          <div className="flex items-center gap-2 bg-white rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm">
            <Users className="h-4 w-4 text-[#64748b]" />
            <span className="text-[#64748b]">Client:</span>
            <span className="font-medium text-[#0f172a]">
              {selectedClient.name}
            </span>
            <span className="text-[#94a3b8]">({selectedClient.client_code})</span>
          </div>
        )}
      </div>

      {/* Empty state when no clients exist */}
      {clients.length === 0 ? (
        <div className="flex items-center justify-center bg-white rounded-xl border border-[#e2e8f0] p-12">
          <div className="text-center">
            <Users className="h-8 w-8 text-[#94a3b8] mx-auto mb-2" />
            <p className="text-sm text-[#64748b]">No clients found. No accounts to display.</p>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-12 gap-6">
          {/* Accounts List */}
          <div className={safeSelectedAccount ? "col-span-5" : "col-span-12"}>
            <FilterBar
              searchPlaceholder="Search account alias or number..."
              searchValue={searchText}
              onSearchChange={setSearchText}
              filters={[
                {
                  key: "env",
                  label: "Environment",
                  options: [
                    { label: "Paper", value: "paper" },
                    { label: "Live", value: "live" },
                  ],
                  value: envFilter,
                  onChange: setEnvFilter,
                },
              ]}
              onClearAll={() => {
                setSearchText("");
                setEnvFilter("");
              }}
            />
            <DataTable
              columns={accountColumns}
              data={filteredAccounts}
              onRowClick={(row) => setSelectedAccount(row.account_id)}
              selectedId={safeSelectedAccount}
              idKey="account_id"
              emptyMessage="No accounts found for this client."
            />
          </div>

          {/* Account Detail Panel */}
          {safeSelectedAccount && selectedAccountDetail ? (
            <div className="col-span-7 space-y-4">
              {/* Locked warning */}
              {selectedAccountDetail.status === "locked" && (
                <div className="flex items-center gap-2 bg-[#fef2f2] border border-[#f87171] rounded-lg px-4 py-3">
                  <Lock className="h-4 w-4 text-[#dc2626]" />
                  <strong className="text-sm text-[#dc2626]">Account Locked</strong>
                  <span className="text-sm text-[#dc2626]">
                    Trading and modifications are restricted.
                  </span>
                </div>
              )}

              {/* Account Detail card */}
              <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold text-[#0f172a]">Account Detail</h3>
                  <button
                    onClick={() => setSelectedAccount(null)}
                    className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
                <dl className="grid grid-cols-2 gap-4">
                  <div>
                    <dt className="text-sm text-[#64748b]">Account #</dt>
                    <dd className="text-sm font-medium text-[#0f172a] mt-0.5">
                      {selectedAccountDetail.account_masked ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-[#64748b]">Alias</dt>
                    <dd className="text-sm font-medium text-[#0f172a] mt-0.5">
                      {selectedAccountDetail.account_alias ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-[#64748b]">Environment</dt>
                    <dd className="mt-0.5">
                      <StatusBadge
                        variant={
                          selectedAccountDetail.environment === "live"
                            ? "warning"
                            : "info"
                        }
                      >
                        {selectedAccountDetail.environment.toUpperCase()}
                      </StatusBadge>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-[#64748b]">Status</dt>
                    <dd className="mt-0.5">
                      <StatusBadge
                        variant={
                          selectedAccountDetail.status === "active"
                            ? "success"
                            : "warning"
                        }
                      >
                        {selectedAccountDetail.status.toUpperCase()}
                      </StatusBadge>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-[#64748b]">Broker Account ID</dt>
                    <dd className="text-sm font-mono text-[#0f172a] mt-0.5">
                      {truncateUuid(selectedAccountDetail.broker_account_id)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-[#64748b]">Client ID</dt>
                    <dd className="text-sm font-mono text-[#0f172a] mt-0.5">
                      {truncateUuid(selectedAccountDetail.client_id)}
                    </dd>
                  </div>
                </dl>
              </div>

              {detailLoading ? (
                <LoadingSpinner text="Loading account detail..." />
              ) : (
                <>
                  {/* Summary cards */}
                  <div className="grid grid-cols-3 gap-4">
                    <div className="bg-white rounded-xl border border-[#e2e8f0] p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <div className="p-1.5 rounded-lg bg-[#eef2ff] text-[#6366f1]">
                          <Wallet className="h-4 w-4" />
                        </div>
                      </div>
                      <p className="text-2xl font-semibold text-[#0f172a]">
                        {formatCurrency(totalValue)}
                      </p>
                      <p className="text-xs text-[#64748b] mt-1">Total Value</p>
                    </div>
                    <div className="bg-white rounded-xl border border-[#e2e8f0] p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <div className="p-1.5 rounded-lg bg-[#ecfdf5] text-[#10b981]">
                          <Wallet className="h-4 w-4" />
                        </div>
                      </div>
                      <p className="text-2xl font-semibold text-[#0f172a]">
                        {cashBalance
                          ? formatCurrency(cashBalance.settled_cash)
                          : "—"}
                      </p>
                      <p className="text-xs text-[#64748b] mt-1">Cash Balance</p>
                    </div>
                    <div className="bg-white rounded-xl border border-[#e2e8f0] p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <div
                          className={`p-1.5 rounded-lg ${
                            totalPnl >= 0
                              ? "bg-[#ecfdf5] text-[#10b981]"
                              : "bg-[#fef2f2] text-[#ef4444]"
                          }`}
                        >
                          {totalPnl >= 0 ? (
                            <TrendingUp className="h-4 w-4" />
                          ) : (
                            <TrendingDown className="h-4 w-4" />
                          )}
                        </div>
                      </div>
                      <p
                        className={`text-2xl font-semibold ${
                          totalPnl >= 0 ? "text-[#16a34a]" : "text-[#dc2626]"
                        }`}
                      >
                        {totalPnl >= 0 ? "+" : ""}
                        {formatCurrency(totalPnl)}
                      </p>
                      <p className="text-xs text-[#64748b] mt-1">Unrealized P&L</p>
                    </div>
                  </div>

                  {/* Cash balance detail */}
                  {cashBalance && (
                    <div className="bg-white rounded-xl border border-[#e2e8f0] p-4">
                      <h4 className="text-sm font-medium text-[#0f172a] mb-3">
                        Cash Balance Detail
                      </h4>
                      <div className="flex gap-6 text-sm flex-wrap">
                        <div>
                          <span className="text-[#64748b]">Available: </span>
                          <span className="font-semibold text-[#0f172a]">
                            {formatCurrency(cashBalance.available_cash)}
                          </span>
                        </div>
                        <div>
                          <span className="text-[#64748b]">Settled: </span>
                          <span className="font-semibold text-[#0f172a]">
                            {formatCurrency(cashBalance.settled_cash)}
                          </span>
                        </div>
                        <div>
                          <span className="text-[#64748b]">Unsettled: </span>
                          <span className="font-semibold text-[#0f172a]">
                            {formatCurrency(cashBalance.unsettled_cash)}
                          </span>
                        </div>
                        <div>
                          <span className="text-[#64748b]">Currency: </span>
                          <span className="font-semibold text-[#0f172a]">
                            {cashBalance.currency}
                          </span>
                        </div>
                        <div>
                          <span className="text-[#64748b]">Source: </span>
                          <span className="font-semibold text-[#0f172a]">
                            {cashBalance.source_of_truth}
                          </span>
                        </div>
                        <div>
                          <span className="text-[#64748b]">Snapshot: </span>
                          <span className="font-semibold text-[#0f172a]">
                            {cashBalance.snapshot_at}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Positions table */}
                  <div className="space-y-2">
                    <h4 className="text-sm font-medium text-[#0f172a]">Positions</h4>
                    <DataTable
                      columns={positionColumns}
                      data={positions}
                      idKey="position_snapshot_id"
                      emptyMessage="No positions for this account."
                      compact
                    />
                  </div>
                </>
              )}
            </div>
          ) : (
            !loading && accounts.length > 0 && (
              <div className="col-span-7 flex items-center justify-center bg-white rounded-xl border border-[#e2e8f0] p-12">
                <div className="text-center">
                  <Wallet className="h-8 w-8 text-[#94a3b8] mx-auto mb-2" />
                  <p className="text-sm text-[#94a3b8]">
                    Select an account from the left panel to view details.
                  </p>
                </div>
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}
