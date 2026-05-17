import { useState } from "react"
import { FilterBar } from "@/components/FilterBar"
import { DataTable } from "@/components/DataTable"
import { StatusBadge } from "@/components/StatusBadge"
import { ChevronLeft, ChevronRight, X } from "lucide-react"

// Mock data
const ordersData = [
  { id: "ORD-20240115-001", symbol: "005930", side: "매수", quantity: 100, status: "체결", createdAt: "2024-01-15 14:32:15 KST", price: 71500, dcId: "DC-001", tdId: "TD-001" },
  { id: "ORD-20240115-002", symbol: "035420", side: "매도", quantity: 50, status: "부분체결", createdAt: "2024-01-15 14:28:42 KST", price: 195000, dcId: "DC-002", tdId: "TD-002" },
  { id: "ORD-20240115-003", symbol: "000660", side: "매수", quantity: 25, status: "실행중", createdAt: "2024-01-15 14:25:19 KST", price: 138000, dcId: "DC-003", tdId: "TD-003" },
  { id: "ORD-20240115-004", symbol: "051910", side: "매도", quantity: 30, status: "체결", createdAt: "2024-01-15 14:20:08 KST", price: 520000, dcId: "DC-004", tdId: "TD-004" },
  { id: "ORD-20240115-005", symbol: "006400", side: "매수", quantity: 15, status: "거부", createdAt: "2024-01-15 14:15:33 KST", price: 312000, dcId: "DC-005", tdId: "TD-005" },
  { id: "ORD-20240115-006", symbol: "035720", side: "매수", quantity: 80, status: "체결", createdAt: "2024-01-15 14:10:22 KST", price: 58200, dcId: "DC-006", tdId: "TD-006" },
]

const stateEventsData = [
  { id: 1, state: "생성", timestamp: "2024-01-15 14:32:15 KST", message: "주문 생성됨" },
  { id: 2, state: "제출", timestamp: "2024-01-15 14:32:16 KST", message: "브로커에 제출됨" },
  { id: 3, state: "접수", timestamp: "2024-01-15 14:32:17 KST", message: "브로커 접수 완료" },
  { id: 4, state: "체결", timestamp: "2024-01-15 14:32:25 KST", message: "100주 전량 체결" },
]

const brokerOrdersData = [
  { id: "BRK-001", odno: "123456789", quantity: 100, filledQty: 100, status: "체결", avgPrice: 71500 },
]

export function OrderTracking() {
  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [sideFilter, setSideFilter] = useState("")
  const [selectedOrder, setSelectedOrder] = useState<typeof ordersData[0] | null>(null)
  const [pageSize, setPageSize] = useState(5)
  const [currentPage, setCurrentPage] = useState(1)

  const filteredOrders = ordersData.filter((order) => {
    const matchesSearch = order.symbol.toLowerCase().includes(search.toLowerCase()) ||
      order.id.toLowerCase().includes(search.toLowerCase())
    const matchesStatus = !statusFilter || order.status === statusFilter
    const matchesSide = !sideFilter || order.side === sideFilter
    return matchesSearch && matchesStatus && matchesSide
  })

  const totalPages = Math.max(1, Math.ceil(filteredOrders.length / pageSize))
  const safePage = Math.min(currentPage, totalPages)
  const pagedOrders = filteredOrders.slice((safePage - 1) * pageSize, safePage * pageSize)

  const handlePageSizeChange = (size: number) => {
    setPageSize(size)
    setCurrentPage(1)
  }

  const handleSearchChange = (v: string) => { setSearch(v); setCurrentPage(1) }
  const handleStatusChange = (v: string) => { setStatusFilter(v); setCurrentPage(1) }
  const handleSideChange = (v: string) => { setSideFilter(v); setCurrentPage(1) }

  const orderColumns = [
    { key: "id", header: "주문 ID", width: "150px" },
    { key: "symbol", header: "종목", render: (value: string) => (
      <span className="font-semibold text-[#0f172a]">{value}</span>
    )},
    { key: "side", header: "구분", render: (value: string) => (
      <StatusBadge variant={value === "매수" ? "success" : "error"}>{value}</StatusBadge>
    )},
    { key: "quantity", header: "수량", render: (value: number) => `${value}주` },
    { key: "price", header: "가격", render: (value: number) => `${value.toLocaleString("ko-KR")}원` },
    { key: "status", header: "상태", render: (value: string) => {
      const variants: Record<string, "success" | "warning" | "error" | "info"> = {
        "체결": "success",
        "부분체결": "warning",
        "실행중": "info",
        "거부": "error",
      }
      return <StatusBadge variant={variants[value] || "neutral"}>{value}</StatusBadge>
    }},
    { key: "createdAt", header: "생성 시간", width: "150px" },
  ]

  const stateColumns = [
    { key: "state", header: "상태", width: "80px" },
    { key: "timestamp", header: "시간", width: "150px" },
    { key: "message", header: "메시지" },
  ]

  const brokerColumns = [
    { key: "odno", header: "ODNO", width: "120px" },
    { key: "quantity", header: "주문 수량" },
    { key: "filledQty", header: "체결 수량" },
    { key: "status", header: "상태", render: (value: string) => (
      <StatusBadge variant={value === "체결" ? "success" : "warning"}>{value}</StatusBadge>
    )},
    { key: "avgPrice", header: "평균가", render: (value: number) => `${value.toLocaleString("ko-KR")}원` },
  ]

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">주문 추적</h1>
        <p className="text-sm text-[#64748b] mt-1">AI 판단에서 실제 주문 제출까지 추적</p>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Orders List */}
        <div className={selectedOrder ? "col-span-7" : "col-span-12"}>
          <FilterBar
            searchPlaceholder="종목 또는 주문 ID 검색..."
            searchValue={search}
            onSearchChange={handleSearchChange}
            filters={[
              {
                key: "status",
                label: "상태",
                options: [
                  { label: "체결", value: "체결" },
                  { label: "부분체결", value: "부분체결" },
                  { label: "실행중", value: "실행중" },
                  { label: "거부", value: "거부" },
                ],
                value: statusFilter,
                onChange: handleStatusChange,
              },
              {
                key: "side",
                label: "구분",
                options: [
                  { label: "매수", value: "매수" },
                  { label: "매도", value: "매도" },
                ],
                value: sideFilter,
                onChange: handleSideChange,
              },
            ]}
            onClearAll={() => {
              handleSearchChange("")
              handleStatusChange("")
              handleSideChange("")
            }}
          />
          <DataTable
            columns={orderColumns}
            data={pagedOrders}
            onRowClick={setSelectedOrder}
            selectedId={selectedOrder?.id}
            idKey="id"
          />

          {/* Pagination bar */}
          <div className="flex items-center justify-between mt-3 px-1">
            <span className="text-xs text-[#94a3b8]">
              총 {filteredOrders.length}건
            </span>
            <div className="flex items-center gap-3">
              {/* Page navigation */}
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={safePage === 1}
                  className="p-1 rounded border border-[#e2e8f0] text-[#64748b] hover:bg-[#f1f5f9] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </button>
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
                  <button
                    key={page}
                    onClick={() => setCurrentPage(page)}
                    className={`min-w-[28px] h-[28px] rounded border text-xs font-medium transition-colors ${
                      page === safePage
                        ? "bg-[#3b82f6] border-[#3b82f6] text-white"
                        : "border-[#e2e8f0] text-[#64748b] hover:bg-[#f1f5f9]"
                    }`}
                  >
                    {page}
                  </button>
                ))}
                <button
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  disabled={safePage === totalPages}
                  className="p-1 rounded border border-[#e2e8f0] text-[#64748b] hover:bg-[#f1f5f9] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>

              {/* Page size selector */}
              <select
                value={pageSize}
                onChange={(e) => handlePageSizeChange(Number(e.target.value))}
                className="h-[28px] rounded border border-[#e2e8f0] bg-white px-2 text-xs text-[#374151] focus:outline-none focus:ring-1 focus:ring-[#3b82f6] cursor-pointer"
              >
                {[5, 10, 20, 50].map((n) => (
                  <option key={n} value={n}>{n}건씩 보기</option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Order Detail Panel */}
        {selectedOrder && (
          <div className="col-span-5 space-y-4">
            {/* Order Info Card */}
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-[#0f172a]">주문 상세</h3>
                <button
                  onClick={() => setSelectedOrder(null)}
                  className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <dl className="grid grid-cols-2 gap-4">
                <div>
                  <dt className="text-sm text-[#64748b]">주문 ID</dt>
                  <dd className="text-sm font-mono font-medium text-[#0f172a] mt-0.5">{selectedOrder.id}</dd>
                </div>
                <div>
                  <dt className="text-sm text-[#64748b]">종목</dt>
                  <dd className="text-sm font-semibold text-[#0f172a] mt-0.5">{selectedOrder.symbol}</dd>
                </div>
                <div>
                  <dt className="text-sm text-[#64748b]">구분</dt>
                  <dd className="mt-0.5">
                    <StatusBadge variant={selectedOrder.side === "매수" ? "success" : "error"}>
                      {selectedOrder.side}
                    </StatusBadge>
                  </dd>
                </div>
                <div>
                  <dt className="text-sm text-[#64748b]">상태</dt>
                  <dd className="mt-0.5">
                    <StatusBadge variant={selectedOrder.status === "체결" ? "success" : "warning"}>
                      {selectedOrder.status}
                    </StatusBadge>
                  </dd>
                </div>
                <div>
                  <dt className="text-sm text-[#64748b]">수량</dt>
                  <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{selectedOrder.quantity}주</dd>
                </div>
                <div>
                  <dt className="text-sm text-[#64748b]">가격</dt>
                  <dd className="text-sm font-medium text-[#0f172a] mt-0.5">{selectedOrder.price.toLocaleString("ko-KR")}원</dd>
                </div>
              </dl>
            </div>

            {/* State Timeline */}
            <div className="space-y-2">
              <h4 className="text-sm font-medium text-[#0f172a]">상태 전이 타임라인</h4>
              <DataTable columns={stateColumns} data={stateEventsData} idKey="id" />
            </div>

            {/* Broker Orders */}
            <div className="space-y-2">
              <h4 className="text-sm font-medium text-[#0f172a]">브로커 주문</h4>
              <DataTable columns={brokerColumns} data={brokerOrdersData} idKey="id" />
            </div>

            {/* Submission Path Summary */}
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
              <h4 className="text-sm font-medium text-[#0f172a] mb-4">제출 경로 요약</h4>
              <div className="space-y-3">
                <div className="flex items-center justify-between py-2 border-b border-[#f1f5f9]">
                  <span className="text-sm text-[#64748b]">Decision Context</span>
                  <span className="text-sm font-mono font-medium text-[#3b82f6]">{selectedOrder.dcId}</span>
                </div>
                <div className="flex items-center justify-between py-2 border-b border-[#f1f5f9]">
                  <span className="text-sm text-[#64748b]">Trade Decision</span>
                  <span className="text-sm font-mono font-medium text-[#3b82f6]">{selectedOrder.tdId}</span>
                </div>
                <div className="flex items-center justify-between py-2">
                  <span className="text-sm text-[#64748b]">Agent Runs</span>
                  <span className="text-sm font-mono font-medium text-[#3b82f6]">EI-001, Risk-001</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
