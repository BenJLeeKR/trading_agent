import { useEffect, useMemo, useState } from "react";
import type { AccountSummary, OrderSummary, PositionSnapshotView, CashBalanceSnapshotView } from "../types/api";
import { getAccounts, getOrders, getPositions, getCashBalance } from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { FilterBar } from "./common/FilterBar";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import type { Column } from "./common/DataTable";
import { Lock, Wallet, TrendingUp, TrendingDown, X } from "lucide-react";

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
  const [typeFilter, setTypeFilter] = useState("");

  // Phase 1: get orders to obtain a client_id (temporary heuristic),
  // then Phase 2: fetch accounts scoped to that client.
  useEffect(() => {
    setLoading(true);
    setError(null);
    // Backend /accounts requires a client_id query parameter, which we cannot
    // derive from /orders alone (OrderSummary has no client_id).
    // Show empty state until a proper client selection mechanism is added.
    setAccounts([]);
    setLoading(false);
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
      const matchType = !typeFilter || a.account_type === typeFilter;
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

  const accountColumns: Column<AccountSummary>[] = [
    { key: "account_code", header: "Account Code" },
    { key: "client_code", header: "Client Code" },
    {
      key: "account_type",
      header: "Type",
      render: (r) => <StatusBadge variant={r.account_type === "margin" ? "info" : "neutral"}>{r.account_type.toUpperCase()}</StatusBadge>,
    },
    {
      key: "status",
      header: "Status",
      render: (r) => {
        const variant = r.status === "active" ? "success" : r.status === "locked" ? "error" : r.status === "pending" ? "warning" : "info";
        return <StatusBadge variant={variant}>{r.status.toUpperCase()}</StatusBadge>;
      },
    },
  ];

  const positionColumns: Column<PositionSnapshotView>[] = [
    { key: "symbol", header: "Symbol" },
    {
      key: "side",
      header: "Side",
      render: (r) => (
        <span className={`text-xs font-semibold ${r.side.toLowerCase() === "long" ? "text-[#16a34a]" : "text-[#dc2626]"}`}>
          {r.side.toUpperCase()}
        </span>
      ),
    },
    { key: "quantity", header: "Qty", render: (r) => formatQty(r.quantity) },
    { key: "avg_price", header: "Avg Cost", render: (r) => formatCurrency(r.avg_price) },
    { key: "current_price", header: "Current Price", render: (r) => formatCurrency(r.current_price) },
    {
      key: "pnl",
      header: "P&L",
      render: (r) => {
        const pnl = Number.parseFloat(r.pnl) || 0;
        return (
          <span className={`text-xs font-semibold ${pnl >= 0 ? "text-[#16a34a]" : "text-[#dc2626]"}`}>
            {pnl >= 0 ? "+" : ""}{formatCurrency(pnl)}
          </span>
        );
      },
    },
    { key: "snapshot_time", header: "Snapshot" },
  ];

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">Accounts</h1>
        <p className="text-sm text-[#64748b] mt-1">View account status, positions, and cash balances</p>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Accounts List */}
        <div className={safeSelectedAccount ? "col-span-5" : "col-span-12"}>
          <FilterBar
            searchPlaceholder="Search account or client code..."
            searchValue={searchText}
            onSearchChange={setSearchText}
            filters={[
              {
                key: "type",
                label: "Account Type",
                options: [
                  { label: "Margin", value: "margin" },
                  { label: "Cash", value: "cash" },
                ],
                value: typeFilter,
                onChange: setTypeFilter,
              },
            ]}
            onClearAll={() => {
              setSearchText("");
              setTypeFilter("");
            }}
          />
          <DataTable
            columns={accountColumns}
            data={filteredAccounts}
            onRowClick={(row) => setSelectedAccount(row.account_id)}
            selectedId={safeSelectedAccount}
            idKey="account_id"
            emptyMessage="No accounts found."
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
                <span className="text-sm text-[#dc2626]">Trading and modifications are restricted.</span>
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
                  <dt className="text-sm text-[#64748b]">Account Code</dt>
                  <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{selectedAccountDetail.account_code}</dd>
                </div>
                <div>
                  <dt className="text-sm text-[#64748b]">Client Code</dt>
                  <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{selectedAccountDetail.client_code}</dd>
                </div>
                <div>
                  <dt className="text-sm text-[#64748b]">Account Type</dt>
                  <dd className="mt-0.5"><StatusBadge variant="info">{selectedAccountDetail.account_type.toUpperCase()}</StatusBadge></dd>
                </div>
                <div>
                  <dt className="text-sm text-[#64748b]">Status</dt>
                  <dd className="mt-0.5">
                    <StatusBadge variant={selectedAccountDetail.status === "active" ? "success" : "warning"}>
                      {selectedAccountDetail.status.toUpperCase()}
                    </StatusBadge>
                  </dd>
                </div>
                <div>
                  <dt className="text-sm text-[#64748b]">Currency</dt>
                  <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{selectedAccountDetail.currency}</dd>
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
                    <p className="text-2xl font-semibold text-[#0f172a]">{formatCurrency(totalValue)}</p>
                    <p className="text-xs text-[#64748b] mt-1">Total Value</p>
                  </div>
                  <div className="bg-white rounded-xl border border-[#e2e8f0] p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="p-1.5 rounded-lg bg-[#ecfdf5] text-[#10b981]">
                        <Wallet className="h-4 w-4" />
                      </div>
                    </div>
                    <p className="text-2xl font-semibold text-[#0f172a]">{cashBalance ? formatCurrency(cashBalance.total_amount) : "—"}</p>
                    <p className="text-xs text-[#64748b] mt-1">Cash Balance</p>
                  </div>
                  <div className="bg-white rounded-xl border border-[#e2e8f0] p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <div className={`p-1.5 rounded-lg ${totalPnl >= 0 ? "bg-[#ecfdf5] text-[#10b981]" : "bg-[#fef2f2] text-[#ef4444]"}`}>
                        {totalPnl >= 0 ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
                      </div>
                    </div>
                    <p className={`text-2xl font-semibold ${totalPnl >= 0 ? "text-[#16a34a]" : "text-[#dc2626]"}`}>
                      {totalPnl >= 0 ? "+" : ""}{formatCurrency(totalPnl)}
                    </p>
                    <p className="text-xs text-[#64748b] mt-1">Day P&L</p>
                  </div>
                </div>

                {/* Cash balance detail */}
                {cashBalance && (
                  <div className="bg-white rounded-xl border border-[#e2e8f0] p-4">
                    <h4 className="text-sm font-medium text-[#0f172a] mb-3">Cash Balance Detail</h4>
                    <div className="flex gap-6 text-sm">
                      <div>
                        <span className="text-[#64748b]">Available: </span>
                        <span className="font-semibold text-[#0f172a]">{formatCurrency(cashBalance.available_amount)}</span>
                      </div>
                      <div>
                        <span className="text-[#64748b]">Currency: </span>
                        <span className="font-semibold text-[#0f172a]">{cashBalance.currency}</span>
                      </div>
                      <div>
                        <span className="text-[#64748b]">Snapshot: </span>
                        <span className="font-semibold text-[#0f172a]">{cashBalance.snapshot_time}</span>
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
                <p className="text-sm text-[#94a3b8]">Select an account from the left panel to view details.</p>
              </div>
            </div>
          )
        )}
      </div>
    </div>
  );
}
