import { StatusCard } from "@/components/StatusCard"
import { DataTable } from "@/components/DataTable"
import { StatusBadge } from "@/components/StatusBadge"
import { WarningBanner } from "@/components/WarningBanner"
import { ArrowRight } from "lucide-react"

// Mock data
const recentOrders = [
  { id: "ORD-001", symbol: "AAPL", side: "BUY", quantity: 100, status: "FILLED", createdAt: "2024-01-15 09:30:00" },
  { id: "ORD-002", symbol: "GOOGL", side: "SELL", quantity: 50, status: "PENDING", createdAt: "2024-01-15 09:28:00" },
  { id: "ORD-003", symbol: "MSFT", side: "BUY", quantity: 200, status: "FILLED", createdAt: "2024-01-15 09:25:00" },
  { id: "ORD-004", symbol: "TSLA", side: "BUY", quantity: 75, status: "REJECTED", createdAt: "2024-01-15 09:20:00" },
  { id: "ORD-005", symbol: "NVDA", side: "SELL", quantity: 150, status: "FILLED", createdAt: "2024-01-15 09:15:00" },
]

const recentLocks = [
  { id: "LOCK-001", type: "RECONCILIATION", account: "ACC-001", createdAt: "2024-01-15 09:00:00" },
  { id: "LOCK-002", type: "POSITION_SYNC", account: "ACC-003", createdAt: "2024-01-15 08:45:00" },
]

interface OverviewProps {
  onNavigate?: (page: string) => void
}

export function Overview({ onNavigate }: OverviewProps) {
  const orderColumns = [
    { key: "id", header: "Order ID", width: "120px" },
    { key: "symbol", header: "Symbol" },
    { key: "side", header: "Side", render: (value: string) => (
      <StatusBadge variant={value === "BUY" ? "success" : "error"}>{value}</StatusBadge>
    )},
    { key: "quantity", header: "Qty" },
    { key: "status", header: "Status", render: (value: string) => {
      const variant = value === "FILLED" ? "success" : value === "PENDING" ? "warning" : "error"
      return <StatusBadge variant={variant}>{value}</StatusBadge>
    }},
    { key: "createdAt", header: "Created" },
  ]

  const lockColumns = [
    { key: "id", header: "Lock ID" },
    { key: "type", header: "Type" },
    { key: "account", header: "Account" },
    { key: "createdAt", header: "Created" },
  ]

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">Overview</h1>
        <p className="text-sm text-[#64748b] mt-1">System status and recent activity</p>
      </div>

      {/* Warning Banner */}
      {recentLocks.length > 0 && (
        <WarningBanner
          variant="warning"
          title={`${recentLocks.length} Active Locks`}
          message="There are active reconciliation locks that may affect order processing."
        />
      )}

      {/* Status Summary Cards */}
      <div className="grid grid-cols-5 gap-4">
        <StatusCard
          title="API Health"
          value="Operational"
          status="healthy"
          subtitle="Last checked 30s ago"
        />
        <StatusCard
          title="Database Health"
          value="Operational"
          status="healthy"
          subtitle="Connection pool: 8/20"
        />
        <StatusCard
          title="Recent Orders"
          value={recentOrders.length}
          status="neutral"
          subtitle="Last 24 hours"
        />
        <StatusCard
          title="Active Locks"
          value={recentLocks.length}
          status={recentLocks.length > 0 ? "warning" : "healthy"}
          subtitle="Blocking operations"
        />
        <StatusCard
          title="Incomplete Recon"
          value={1}
          status="warning"
          subtitle="Pending resolution"
        />
      </div>

      {/* Recent Orders Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">Recent Orders</h2>
          <button
            onClick={() => onNavigate?.("Orders")}
            className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
          >
            View all orders
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
        <DataTable columns={orderColumns} data={recentOrders} idKey="id" />
      </div>

      {/* Active Locks Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">Active Locks</h2>
          <button
            onClick={() => onNavigate?.("Reconciliation")}
            className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
          >
            View reconciliation
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
        {recentLocks.length > 0 ? (
          <DataTable columns={lockColumns} data={recentLocks} idKey="id" />
        ) : (
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
            <p className="text-sm text-[#94a3b8]">No active locks</p>
          </div>
        )}
      </div>
    </div>
  )
}
