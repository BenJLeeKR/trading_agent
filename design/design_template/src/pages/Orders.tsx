import { useState } from "react"
import { FilterBar } from "@/components/FilterBar"
import { DataTable } from "@/components/DataTable"
import { StatusBadge } from "@/components/StatusBadge"
import { X } from "lucide-react"

// Mock data
const ordersData = [
  { id: "ORD-001", symbol: "AAPL", side: "BUY", quantity: 100, status: "FILLED", correlationId: "CORR-001", createdAt: "2024-01-15 09:30:00" },
  { id: "ORD-002", symbol: "GOOGL", side: "SELL", quantity: 50, status: "PENDING", correlationId: "CORR-002", createdAt: "2024-01-15 09:28:00" },
  { id: "ORD-003", symbol: "MSFT", side: "BUY", quantity: 200, status: "FILLED", correlationId: "CORR-003", createdAt: "2024-01-15 09:25:00" },
  { id: "ORD-004", symbol: "TSLA", side: "BUY", quantity: 75, status: "REJECTED", correlationId: "CORR-004", createdAt: "2024-01-15 09:20:00" },
  { id: "ORD-005", symbol: "NVDA", side: "SELL", quantity: 150, status: "FILLED", correlationId: "CORR-005", createdAt: "2024-01-15 09:15:00" },
  { id: "ORD-006", symbol: "AMD", side: "BUY", quantity: 300, status: "PARTIAL", correlationId: "CORR-006", createdAt: "2024-01-15 09:10:00" },
  { id: "ORD-007", symbol: "META", side: "SELL", quantity: 80, status: "FILLED", correlationId: "CORR-007", createdAt: "2024-01-15 09:05:00" },
]

const stateEvents = [
  { id: 1, state: "CREATED", timestamp: "2024-01-15 09:30:00", message: "Order created" },
  { id: 2, state: "SUBMITTED", timestamp: "2024-01-15 09:30:01", message: "Submitted to broker" },
  { id: 3, state: "ACKNOWLEDGED", timestamp: "2024-01-15 09:30:02", message: "Broker acknowledged" },
  { id: 4, state: "FILLED", timestamp: "2024-01-15 09:30:05", message: "Order fully filled" },
]

const brokerOrders = [
  { id: "BRK-001", brokerId: "IB-12345", status: "FILLED", filledQty: 100, avgPrice: 185.50 },
]

export function Orders() {
  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [sideFilter, setSideFilter] = useState("")
  const [selectedOrder, setSelectedOrder] = useState<typeof ordersData[0] | null>(null)

  const filteredOrders = ordersData.filter((order) => {
    const matchesSearch = order.symbol.toLowerCase().includes(search.toLowerCase()) ||
      order.id.toLowerCase().includes(search.toLowerCase())
    const matchesStatus = !statusFilter || order.status === statusFilter
    const matchesSide = !sideFilter || order.side === sideFilter
    return matchesSearch && matchesStatus && matchesSide
  })

  const orderColumns = [
    { key: "id", header: "Order ID", width: "100px" },
    { key: "symbol", header: "Symbol" },
    { key: "side", header: "Side", render: (value: string) => (
      <StatusBadge variant={value === "BUY" ? "success" : "error"}>{value}</StatusBadge>
    )},
    { key: "quantity", header: "Qty" },
    { key: "status", header: "Status", render: (value: string) => {
      const variants: Record<string, "success" | "warning" | "error" | "info"> = {
        FILLED: "success",
        PENDING: "warning",
        REJECTED: "error",
        PARTIAL: "info",
      }
      return <StatusBadge variant={variants[value] || "neutral"}>{value}</StatusBadge>
    }},
    { key: "correlationId", header: "Correlation ID" },
    { key: "createdAt", header: "Created" },
  ]

  const stateColumns = [
    { key: "state", header: "State" },
    { key: "timestamp", header: "Timestamp" },
    { key: "message", header: "Message" },
  ]

  const brokerColumns = [
    { key: "id", header: "ID" },
    { key: "brokerId", header: "Broker ID" },
    { key: "status", header: "Status" },
    { key: "filledQty", header: "Filled Qty" },
    { key: "avgPrice", header: "Avg Price", render: (value: number) => `$${value.toFixed(2)}` },
  ]

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">Orders</h1>
        <p className="text-sm text-[#64748b] mt-1">View order lifecycle, broker mapping, and decision lineage</p>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Orders List */}
        <div className={selectedOrder ? "col-span-7" : "col-span-12"}>
          <FilterBar
            searchPlaceholder="Search symbol or order ID..."
            searchValue={search}
            onSearchChange={setSearch}
            filters={[
              {
                key: "status",
                label: "Status",
                options: [
                  { label: "Filled", value: "FILLED" },
                  { label: "Pending", value: "PENDING" },
                  { label: "Rejected", value: "REJECTED" },
                  { label: "Partial", value: "PARTIAL" },
                ],
                value: statusFilter,
                onChange: setStatusFilter,
              },
              {
                key: "side",
                label: "Side",
                options: [
                  { label: "Buy", value: "BUY" },
                  { label: "Sell", value: "SELL" },
                ],
                value: sideFilter,
                onChange: setSideFilter,
              },
            ]}
            onClearAll={() => {
              setSearch("")
              setStatusFilter("")
              setSideFilter("")
            }}
          />
          <DataTable
            columns={orderColumns}
            data={filteredOrders}
            onRowClick={setSelectedOrder}
            selectedId={selectedOrder?.id}
            idKey="id"
          />
        </div>

        {/* Order Detail Panel */}
        {selectedOrder && (
          <div className="col-span-5 space-y-4">
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-[#0f172a]">Order Detail</h3>
                <button
                  onClick={() => setSelectedOrder(null)}
                  className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <dl className="space-y-3">
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Order ID</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedOrder.id}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Symbol</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedOrder.symbol}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Side</dt>
                  <dd><StatusBadge variant={selectedOrder.side === "BUY" ? "success" : "error"}>{selectedOrder.side}</StatusBadge></dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Quantity</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedOrder.quantity}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Status</dt>
                  <dd><StatusBadge variant={selectedOrder.status === "FILLED" ? "success" : "warning"}>{selectedOrder.status}</StatusBadge></dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Correlation ID</dt>
                  <dd className="text-sm font-mono text-[#0f172a]">{selectedOrder.correlationId}</dd>
                </div>
              </dl>
            </div>

            {/* State Events */}
            <div className="space-y-2">
              <h4 className="text-sm font-medium text-[#0f172a]">State Events</h4>
              <DataTable columns={stateColumns} data={stateEvents} idKey="id" />
            </div>

            {/* Broker Orders */}
            <div className="space-y-2">
              <h4 className="text-sm font-medium text-[#0f172a]">Broker Orders</h4>
              <DataTable columns={brokerColumns} data={brokerOrders} idKey="id" />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
