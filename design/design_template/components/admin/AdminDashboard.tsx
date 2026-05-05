'use client'

import { useState } from 'react'
import Sidebar from './Sidebar'
import Header from './Header'
import OverviewPage from './pages/OverviewPage'
import OrdersPage from './pages/OrdersPage'
import ReconciliationPage from './pages/ReconciliationPage'
import AccountsPage from './pages/AccountsPage'
import DecisionsPage from './pages/DecisionsPage'

type Page = 'overview' | 'orders' | 'reconciliation' | 'accounts' | 'decisions'

export default function AdminDashboard() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [activePage, setActivePage] = useState<Page>('overview')

  const renderPage = () => {
    switch (activePage) {
      case 'overview':       return <OverviewPage />
      case 'orders':         return <OrdersPage />
      case 'reconciliation': return <ReconciliationPage />
      case 'accounts':       return <AccountsPage />
      case 'decisions':      return <DecisionsPage />
    }
  }

  return (
    <div className="flex h-screen overflow-hidden" style={{ backgroundColor: '#f4f5f7' }}>
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((v) => !v)}
        activePage={activePage}
        onNavigate={(page) => setActivePage(page as Page)}
      />
      <div className="flex flex-col flex-1 overflow-hidden min-w-0">
        <Header activePage={activePage} />
        <main className="flex-1 overflow-y-auto p-5">
          {renderPage()}
        </main>
      </div>
    </div>
  )
}
