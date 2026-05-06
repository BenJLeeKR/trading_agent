import { useState } from "react"
import { Sidebar } from "@/components/Sidebar"
import { Header } from "@/components/Header"
import { Overview } from "@/pages/Overview"
import { Orders } from "@/pages/Orders"
import { Reconciliation } from "@/pages/Reconciliation"
import { Accounts } from "@/pages/Accounts"
import { Decisions } from "@/pages/Decisions"
import { AgentRuns } from "@/pages/AgentRuns"

type PageType = "Overview" | "Orders" | "Reconciliation" | "Accounts" | "Decisions" | "Agent Runs"

function App() {
  const [currentPage, setCurrentPage] = useState<PageType>("Overview")

  const renderPage = () => {
    switch (currentPage) {
      case "Overview":
        return <Overview onNavigate={(page) => setCurrentPage(page as PageType)} />
      case "Orders":
        return <Orders />
      case "Reconciliation":
        return <Reconciliation />
      case "Accounts":
        return <Accounts />
      case "Decisions":
        return <Decisions />
      case "Agent Runs":
        return <AgentRuns />
      default:
        return <Overview onNavigate={(page) => setCurrentPage(page as PageType)} />
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
