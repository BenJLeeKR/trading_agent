import { useState } from "react"
import { DataTable } from "@/components/DataTable"
import { StatusBadge } from "@/components/StatusBadge"
import { WarningBanner } from "@/components/WarningBanner"
import { X, AlertCircle } from "lucide-react"

// Mock data
const alertsData = [
  { id: "ALT-001", level: "긴급", title: "스냅샷 지연", description: "마지막 스냅샷이 3분 이상 동기화되지 않았습니다.", time: "2024-01-15 14:30:00", status: "OPEN" },
  { id: "ALT-002", level: "주의", title: "정합성 필요 주문 증가", description: "미해결 정합성 상태가 2개로 증가했습니다.", time: "2024-01-15 14:25:00", status: "OPEN" },
  { id: "ALT-003", level: "주의", title: "Pending Submit 재발생", description: "1시간 이상 제출 대기 상태인 주문이 있습니다.", time: "2024-01-15 14:12:00", status: "OPEN" },
  { id: "ALT-004", level: "정보", title: "정합성 상태 정상", description: "모든 포지션과 현금 잔액이 정상 동기화됨.", time: "2024-01-15 14:00:00", status: "RESOLVED" },
  { id: "ALT-005", level: "정보", title: "주문 제출 정상", description: "지난 1시간 동안 모든 주문이 정상 처리됨.", time: "2024-01-15 13:59:00", status: "RESOLVED" },
]

const operationNotes = [
  { id: "NOTE-001", date: "2024-01-15", action: "오전 장 개장 전 포지션 정리", status: "완료" },
  { id: "NOTE-002", date: "2024-01-15", action: "API 토큰 갱신", status: "완료" },
  { id: "NOTE-003", date: "2024-01-16", action: "Pre-Market 점검 필요", status: "대기" },
]

const preMarketChecklist = [
  { id: 1, item: "KIS 환경 상태 확인 (paper/live)" },
  { id: 2, item: "Token cache 유효성 확인" },
  { id: 3, item: "스냅샷 신선도 확인" },
  { id: 4, item: "브로커 용량 상태 확인" },
]

export function OperationsAlerts() {
  const [selectedAlert, setSelectedAlert] = useState<typeof alertsData[0] | null>(null)
  const [levelFilter, setLevelFilter] = useState("")

  const urgentCount = alertsData.filter(a => a.level === "긴급" && a.status === "OPEN").length

  const filteredAlerts = alertsData.filter((alert) => {
    return !levelFilter || alert.level === levelFilter
  })

  const alertColumns = [
    { key: "level", header: "수준", width: "80px", render: (value: string) => {
      const variants: Record<string, "error" | "warning" | "info"> = {
        "긴급": "error",
        "주의": "warning",
        "정보": "info",
      }
      return <StatusBadge variant={variants[value] || "neutral"}>{value}</StatusBadge>
    }},
    { key: "title", header: "제목" },
    { key: "time", header: "발생 시간", width: "150px" },
    { key: "status", header: "상태", width: "100px", render: (value: string) => (
      <StatusBadge variant={value === "OPEN" ? "warning" : "success"}>
        {value === "OPEN" ? "미해결" : "해결됨"}
      </StatusBadge>
    )},
  ]

  const noteColumns = [
    { key: "date", header: "날짜", width: "120px" },
    { key: "action", header: "조치 내용" },
    { key: "status", header: "상태", width: "80px", render: (value: string) => (
      <StatusBadge variant={value === "완료" ? "success" : "warning"}>{value}</StatusBadge>
    )},
  ]

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">운영 경고</h1>
        <p className="text-sm text-[#64748b] mt-1">수동 개입 필요 신호 및 운영 메모</p>
      </div>

      {/* Urgent Warning Banner */}
      {urgentCount > 0 && (
        <WarningBanner
          variant="error"
          title={`즉시 확인 필요: ${urgentCount}건`}
          message="긴급 경고가 발생했습니다. 즉시 확인하고 조치하세요."
        />
      )}

      <div className="grid grid-cols-12 gap-6">
        {/* Alerts List */}
        <div className={selectedAlert ? "col-span-7" : "col-span-12"}>
          {/* Filter Buttons */}
          <div className="flex items-center gap-2 mb-4">
            <button
              onClick={() => setLevelFilter("")}
              className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                levelFilter === "" 
                  ? "bg-[#3b82f6] text-white border-[#3b82f6]" 
                  : "bg-white text-[#64748b] border-[#e2e8f0] hover:border-[#3b82f6]"
              }`}
            >
              전체
            </button>
            <button
              onClick={() => setLevelFilter("긴급")}
              className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                levelFilter === "긴급" 
                  ? "bg-[#dc2626] text-white border-[#dc2626]" 
                  : "bg-white text-[#64748b] border-[#e2e8f0] hover:border-[#dc2626]"
              }`}
            >
              긴급
            </button>
            <button
              onClick={() => setLevelFilter("주의")}
              className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                levelFilter === "주의" 
                  ? "bg-[#f59e0b] text-white border-[#f59e0b]" 
                  : "bg-white text-[#64748b] border-[#e2e8f0] hover:border-[#f59e0b]"
              }`}
            >
              주의
            </button>
            <button
              onClick={() => setLevelFilter("정보")}
              className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                levelFilter === "정보" 
                  ? "bg-[#3b82f6] text-white border-[#3b82f6]" 
                  : "bg-white text-[#64748b] border-[#e2e8f0] hover:border-[#3b82f6]"
              }`}
            >
              정보
            </button>
          </div>

          <DataTable
            columns={alertColumns}
            data={filteredAlerts}
            onRowClick={setSelectedAlert}
            selectedId={selectedAlert?.id}
            idKey="id"
          />
        </div>

        {/* Alert Detail Panel */}
        {selectedAlert && (
          <div className="col-span-5 space-y-4">
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-[#0f172a]">경고 상세</h3>
                <button
                  onClick={() => setSelectedAlert(null)}
                  className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <dl className="space-y-3">
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">ID</dt>
                  <dd className="text-sm font-mono text-[#0f172a]">{selectedAlert.id}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">수준</dt>
                  <dd>
                    <StatusBadge variant={
                      selectedAlert.level === "긴급" ? "error" : 
                      selectedAlert.level === "주의" ? "warning" : "info"
                    }>
                      {selectedAlert.level}
                    </StatusBadge>
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">제목</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedAlert.title}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">상태</dt>
                  <dd>
                    <StatusBadge variant={selectedAlert.status === "OPEN" ? "warning" : "success"}>
                      {selectedAlert.status === "OPEN" ? "미해결" : "해결됨"}
                    </StatusBadge>
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">발생 시간</dt>
                  <dd className="text-sm text-[#0f172a]">{selectedAlert.time}</dd>
                </div>
                <div className="pt-2 border-t border-[#e2e8f0]">
                  <dt className="text-sm text-[#64748b] mb-1">설명</dt>
                  <dd className="text-sm text-[#0f172a]">{selectedAlert.description}</dd>
                </div>
              </dl>
            </div>
          </div>
        )}
      </div>

      {/* Operation Notes Section */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold text-[#0f172a]">운영 메모</h2>
        <DataTable columns={noteColumns} data={operationNotes} idKey="id" />
      </div>

      {/* Pre-Market Checklist */}
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
        <div className="flex items-center gap-2 mb-4">
          <AlertCircle className="h-5 w-5 text-[#3b82f6]" />
          <h3 className="text-lg font-semibold text-[#0f172a]">내일 Pre-Market 확인 사항</h3>
        </div>
        <ul className="space-y-2">
          {preMarketChecklist.map((item) => (
            <li key={item.id} className="flex items-center gap-2 text-sm text-[#475569]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#3b82f6]" />
              {item.item}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
