import { useEffect, useMemo, useState } from "react";
import type { AccountSummary, PositionSnapshotView, CashBalanceSnapshotView } from "../types/api";
import { getAccounts, getPositions, getCashBalance } from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import type { Column } from "./common/DataTable";

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

  useEffect(() => {
    setLoading(true);
    setError(null);
    getAccounts()
      .then(setAccounts)
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

  const accountColumns: Column<AccountSummary>[] = [
    { key: "account_code", label: "Account Code" },
    { key: "client_code", label: "Client Code" },
    { key: "account_type", label: "Type" },
    {
      key: "status",
      label: "Status",
      render: (r) => <StatusBadge status={r.status} />,
    },
    { key: "currency", label: "Currency" },
  ];

  const positionColumns: Column<PositionSnapshotView>[] = [
    { key: "symbol", label: "Symbol" },
    {
      key: "side",
      label: "Side",
      render: (r) => (
        <span
          style={{
            color:
              r.side.toLowerCase() === "long"
                ? "var(--pico-ins-color)"
                : "var(--pico-del-color)",
            fontWeight: 600,
          }}
        >
          {r.side.toUpperCase()}
        </span>
      ),
    },
    { key: "quantity", label: "Qty" },
    { key: "avg_price", label: "Avg Price" },
    { key: "current_price", label: "Current Price" },
    { key: "pnl", label: "PnL" },
    { key: "snapshot_time", label: "Snapshot" },
  ];

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  // Find selected account details for display
  const selectedAccountDetail = safeSelectedAccount
    ? accounts.find((a) => a.account_id === safeSelectedAccount)
    : null;

  return (
    <section>
      <hgroup>
        <h2>Accounts & Positions</h2>
        <p>Select an account to view its positions and cash balance.</p>
      </hgroup>

      {/* Filter bar */}
      <div
        style={{
          display: "flex",
          gap: "0.75rem",
          flexWrap: "wrap",
          marginBottom: "0.75rem",
          alignItems: "flex-end",
        }}
      >
        <label style={{ display: "flex", flexDirection: "column", fontSize: "0.875rem" }}>
          Search
          <input
            type="search"
            placeholder="Search by code or alias..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            aria-label="Search accounts"
            style={{ width: "220px" }}
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", fontSize: "0.875rem" }}>
          Type
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            aria-label="Filter by account type"
            style={{ width: "140px" }}
          >
            <option value="all">All Types</option>
            <option value="cash">Cash</option>
            <option value="margin">Margin</option>
          </select>
        </label>
      </div>

      <DataTable
        columns={accountColumns}
        data={filteredAccounts}
        keyField="account_id"
        onRowClick={(row) => setSelectedAccount(row.account_id)}
        selectedKey={safeSelectedAccount}
        emptyMessage="No accounts found."
      />

      {safeSelectedAccount && (
        <>
          <hr />
          <h3>
            Account Detail:{" "}
            {selectedAccountDetail
              ? `${selectedAccountDetail.account_code} (${selectedAccountDetail.account_type})`
              : safeSelectedAccount}
          </h3>

          {detailLoading ? (
            <LoadingSpinner />
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
                gap: "1rem",
              }}
            >
              <article>
                <header><strong>Cash Balance</strong></header>
                {cashBalance ? (
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: "0.5rem",
                    }}
                  >
                    <div><strong>Currency:</strong> {cashBalance.currency}</div>
                    <div><strong>Available:</strong> {cashBalance.available_amount}</div>
                    <div><strong>Total:</strong> {cashBalance.total_amount}</div>
                    <div><strong>Snapshot:</strong> {cashBalance.snapshot_time}</div>
                  </div>
                ) : (
                  <p style={{ color: "var(--pico-muted-color)" }}>
                    No cash balance snapshot available.
                  </p>
                )}
              </article>

              <article>
                <header>
                  <strong>Positions ({positions.length})</strong>
                </header>
                <DataTable
                  columns={positionColumns}
                  data={positions}
                  keyField="position_snapshot_id"
                  emptyMessage="No positions for this account."
                />
              </article>
            </div>
          )}
        </>
      )}
    </section>
  );
}
