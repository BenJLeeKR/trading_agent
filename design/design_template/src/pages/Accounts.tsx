import { useState } from "react"
import { FilterBar } from "@/components/FilterBar"
import { DataTable } from "@/components/DataTable"
import { StatusBadge } from "@/components/StatusBadge"
import { X } from "lucide-react"

// Mock data
const accountsData = [
  { id: "ACC-001", accountCode: "MAIN-001", clientCode: "CLIENT-A", accountType: "MARGIN", status: "ACTIVE" },
  { id: "ACC-002", accountCode: "MAIN-002", clientCode: "CLIENT-B", accountType: "CASH", status: "ACTIVE" },
  { id: "ACC-003", accountCode: "HEDGE-001", clientCode: "CLIENT-A", accountType: "MARGIN", status: "RESTRICTED" },
  { id: "ACC-004", accountCode: "ALGO-001", clientCode: "CLIENT-C", accountType: "MARGIN", status: "ACTIVE" },
]

const positionsData = [
  { id: 1, symbol: "AAPL", quantity: 500, avgCost: 175.50, marketValue: 92750.00, unrealizedPnL: 4875.00 },
  { id: 2, symbol: "GOOGL", quantity: 100, avgCost: 140.25, marketValue: 14200.00, unrealizedPnL: 175.00 },
  { id: 3, symbol: "MSFT", quantity: 300, avgCost: 380.00, marketValue: 117000.00, unrealizedPnL: 3000.00 },
]

const cashBalances = [
  { id: 1, currency: "USD", balance: 250000.00, available: 185000.00, reserved: 65000.00 },
  { id: 2, currency: "EUR", balance: 50000.00, available: 50000.00, reserved: 0 },
]

export function Accounts() {
  const [search, setSearch] = useState("")
  const [typeFilter, setTypeFilter] = useState("")
  const [selectedAccount, setSelectedAccount] = useState<typeof accountsData[0] | null>(null)

  const filteredAccounts = accountsData.filter((account) => {
    const matchesSearch = account.accountCode.toLowerCase().includes(search.toLowerCase()) ||
      account.clientCode.toLowerCase().includes(search.toLowerCase())
    const matchesType = !typeFilter || account.accountType === typeFilter
    return matchesSearch && matchesType
  })

  const accountColumns = [
    { key: "accountCode", header: "Account Code" },
    { key: "clientCode", header: "Client Code" },
    { key: "accountType", header: "Type", render: (value: string) => (
      <StatusBadge variant={value === "MARGIN" ? "info" : "neutral"}>{value}</StatusBadge>
    )},
    { key: "status", header: "Status", render: (value: string) => (
      <StatusBadge variant={value === "ACTIVE" ? "success" : "warning"}>{value}</StatusBadge>
    )},
  ]

  const positionColumns = [
    { key: "symbol", header: "Symbol" },
    { key: "quantity", header: "Qty" },
    { key: "avgCost", header: "Avg Cost", render: (v: number) => `$${v.toFixed(2)}` },
    { key: "marketValue", header: "Market Value", render: (v: number) => `$${v.toLocaleString()}` },
    { key: "unrealizedPnL", header: "Unrealized P&L", render: (v: number) => (
      <span className={v >= 0 ? "text-[#16a34a]" : "text-[#dc2626]"}>
        {v >= 0 ? "+" : ""}{`$${v.toLocaleString()}`}
      </span>
    )},
  ]

  const cashColumns = [
    { key: "currency", header: "Currency" },
    { key: "balance", header: "Balance", render: (v: number) => `$${v.toLocaleString()}` },
    { key: "available", header: "Available", render: (v: number) => `$${v.toLocaleString()}` },
    { key: "reserved", header: "Reserved", render: (v: number) => `$${v.toLocaleString()}` },
  ]

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">Accounts</h1>
        <p className="text-sm text-[#64748b] mt-1">View account status, positions, and cash balances</p>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Accounts List */}
        <div className={selectedAccount ? "col-span-5" : "col-span-12"}>
          <FilterBar
            searchPlaceholder="Search account or client code..."
            searchValue={search}
            onSearchChange={setSearch}
            filters={[
              {
                key: "type",
                label: "Account Type",
                options: [
                  { label: "Margin", value: "MARGIN" },
                  { label: "Cash", value: "CASH" },
                ],
                value: typeFilter,
                onChange: setTypeFilter,
              },
            ]}
            onClearAll={() => {
              setSearch("")
              setTypeFilter("")
            }}
          />
          <DataTable
            columns={accountColumns}
            data={filteredAccounts}
            onRowClick={setSelectedAccount}
            selectedId={selectedAccount?.id}
            idKey="id"
          />
        </div>

        {/* Account Detail Panel */}
        {selectedAccount && (
          <div className="col-span-7 space-y-4">
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
                  <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{selectedAccount.accountCode}</dd>
                </div>
                <div>
                  <dt className="text-sm text-[#64748b]">Client Code</dt>
                  <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{selectedAccount.clientCode}</dd>
                </div>
                <div>
                  <dt className="text-sm text-[#64748b]">Account Type</dt>
                  <dd className="mt-0.5"><StatusBadge variant="info">{selectedAccount.accountType}</StatusBadge></dd>
                </div>
                <div>
                  <dt className="text-sm text-[#64748b]">Status</dt>
                  <dd className="mt-0.5"><StatusBadge variant={selectedAccount.status === "ACTIVE" ? "success" : "warning"}>{selectedAccount.status}</StatusBadge></dd>
                </div>
              </dl>
            </div>

            {/* Positions */}
            <div className="space-y-2">
              <h4 className="text-sm font-medium text-[#0f172a]">Positions</h4>
              <DataTable columns={positionColumns} data={positionsData} idKey="id" />
            </div>

            {/* Cash Balances */}
            <div className="space-y-2">
              <h4 className="text-sm font-medium text-[#0f172a]">Cash Balances</h4>
              <DataTable columns={cashColumns} data={cashBalances} idKey="id" />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
