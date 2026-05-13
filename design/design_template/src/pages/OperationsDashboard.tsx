import { StatusCard } from "@/components/StatusCard"
import { DataTable } from "@/components/DataTable"
import { StatusBadge } from "@/components/StatusBadge"
import { WarningBanner } from "@/components/WarningBanner"
import { ArrowRight } from "lucide-react"

// Mock data
const recentEvents = [
  { id: "EVT-001", time: "14:32:15", type: "ORDER_SUBMIT", description: "주문 제출", symbol: "AAPL", status: "SUCCESS" },
  { id: "EVT-002", time: "14:30:08", type: "POSITION_SYNC", description: "포지션 동기화", symbol: "-", status: "SUCCESS" },
  { id: "EVT-003", time: "14:28:42", type: "SANITY_CHECK", description: "건전성 점검", symbol: "-", status: "SUCCESS" },
  { id: "EVT-004", time: "14:25:19", type: "AUDIT_LOG", description: "감시 기록", symbol: "MSFT", status: "SUCCESS" },
  { id: "EVT-005", time: "14:20:33", type: "ORDER_SUBMIT", description: "주문 제출", symbol: "GOOGL", status: "SUCCESS" },
]

const pendingReconciliations = [
  { id: "RECON-001", type: "POSITION_MISMATCH", account: "ACC-001", createdAt: "2024-01-15 09:00:00" },
  { id: "RECON-002", type: "CASH_MISMATCH", account: "ACC-003", createdAt: "2024-01-15 08:45:00" },
]

interface OperationsDashboardProps {
  onNavigate?: (page: string) => void
}

export function OperationsDashboard({ onNavigate }: OperationsDashboardProps) {
  const eventColumns = [
    { key: "time", header: "시간", width: "100px" },
    { key: "type", header: "유형", render: (value: string) => (
      <span className="font-mono text-xs text-[#64748b]">{value}</span>
    )},
    { key: "description", header: "설명" },
    { key: "symbol", header: "종목", render: (value: string) => (
      value !== "-" ? (
        <StatusBadge variant="info">{value}</StatusBadge>
      ) : (
        <span className="text-[#94a3b8]">-</span>
      )
    )},
    { key: "status", header: "상태", render: (value: string) => (
      <StatusBadge variant={value === "SUCCESS" ? "success" : "error"}>{value === "SUCCESS" ? "성공" : "실패"}</StatusBadge>
    )},
  ]

  const reconColumns = [
    { key: "id", header: "ID" },
    { key: "type", header: "유형" },
    { key: "account", header: "계좌" },
    { key: "createdAt", header: "발생 시간" },
  ]

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">운영 대시보드</h1>
        <p className="text-sm text-[#64748b] mt-1">시스템 상태 및 오늘의 운영 현황</p>
      </div>

      {/* Warning Banner */}
      {pendingReconciliations.length > 0 && (
        <WarningBanner
          variant="warning"
          title={`미해결 정합성 상태: ${pendingReconciliations.length}건`}
          message="포지션 또는 현금 불일치가 발생했습니다. 정합성 점검 화면에서 확인하세요."
        />
      )}

      {/* Status Summary Cards - single flex-wrap row, same as Overview style */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4">
        <StatusCard
          title="API 상태"
          value="정상"
          status="healthy"
          subtitle="마지막 확인: 30초 전"
        />
        <StatusCard
          title="DB 상태"
          value="정상"
          status="healthy"
          subtitle="연결 풀: 8/20"
        />
        <StatusCard
          title="Ready 상태"
          value="운영 준비"
          status="healthy"
          subtitle="모든 시스템 가동 중"
        />
        <StatusCard
          title="브로커 용량"
          value="여유"
          status="healthy"
          subtitle="일일 한도: 32% 사용"
        />
        <StatusCard
          title="마지막 스냅샷 동기화"
          value="1분 전"
          status="healthy"
          subtitle="다음 동기화: 4분 후"
        />
        <StatusCard
          title="미해결 정합성"
          value={`${pendingReconciliations.length}건`}
          status={pendingReconciliations.length > 0 ? "warning" : "healthy"}
          subtitle="수동 확인 필요"
        />
        <StatusCard
          title="오늘 AI 결정"
          value="156건"
          status="neutral"
          subtitle="승인 142 / 거부 14"
        />
        <StatusCard
          title="오늘 주문 제출"
          value="42건"
          status="neutral"
          subtitle="체결 38 / 대기 4"
        />
        <StatusCard
          title="현재 포지션"
          value="12종목"
          status="neutral"
          subtitle="총 평가액: $892,450"
        />
        <StatusCard
          title="가용 현금"
          value="$125,430"
          status="neutral"
          subtitle="예약금: $65,000"
        />
        <StatusCard
          title="미실현 손익"
          value="+$4,230"
          status="healthy"
          subtitle="+3.3% (전일 대비)"
        />
        <StatusCard
          title="당일 성과"
          value="+$1,850"
          status="healthy"
          subtitle="+1.5%"
        />
      </div>

      {/* Recent Events Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">최근 실행 타임라인</h2>
          <button
            onClick={() => onNavigate?.("주문 추적")}
            className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
          >
            전체 보기
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
        <DataTable columns={eventColumns} data={recentEvents} idKey="id" />
      </div>

      {/* Pending Reconciliations Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">미해결 정합성 상태</h2>
          <button
            onClick={() => onNavigate?.("정합성 점검")}
            className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
          >
            정합성 점검
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
        {pendingReconciliations.length > 0 ? (
          <DataTable columns={reconColumns} data={pendingReconciliations} idKey="id" />
        ) : (
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
            <p className="text-sm text-[#94a3b8]">미해결 정합성 상태 없음</p>
          </div>
        )}
      </div>
    </div>
  )
}
