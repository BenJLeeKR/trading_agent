import { useState } from "react"
import { Sidebar } from "@/components/Sidebar"
import { Header } from "@/components/Header"
import { Overview } from "@/pages/Overview"
import { Orders } from "@/pages/Orders"
import { Reconciliation } from "@/pages/Reconciliation"
import { Accounts } from "@/pages/Accounts"
import { Decisions } from "@/pages/Decisions"
import { AgentRuns } from "@/pages/AgentRuns"
import { OperationsDashboard } from "@/pages/OperationsDashboard"
import { OperationsAlerts } from "@/pages/OperationsAlerts"
import { OrderTracking } from "@/pages/OrderTracking"

type PageType = "운영 대시보드" | "운영 경고" | "주문 추적" | "주문" | "정합성 점검" | "계좌" | "판단" | "에이전트 실행"

function App() {
  const [currentPage, setCurrentPage] = useState<PageType>("운영 대시보드")

  const renderPage = () => {
    switch (currentPage) {
      case "운영 대시보드":
        return <OperationsDashboard />
      case "운영 경고":
        return <OperationsAlerts />
      case "주문 추적":
        return <OrderTracking />
      case "주문":
        return <Orders />
      case "정합성 점검":
        return <Reconciliation />
      case "계좌":
        return <Accounts />
      case "판단":
        return <Decisions />
      case "에이전트 실행":
        return <AgentRuns />
      default:
        return <OperationsDashboard />
    }
  }

  return (
    <div className="flex h-screen bg-[#f8fafc]">
      <Sidebar activeItem={currentPage} onNavigate={(item) => setCurrentPage(item as PageType)} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header />
        <main className="flex-1 overflow-auto">
          {renderPage()}
        </main>
      </div>
    </div>
  )
}

export default App
