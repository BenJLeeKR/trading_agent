'use client'

import { useState } from 'react'
import Sidebar from '../components/admin/Sidebar'
import Header from '../components/admin/Header'
import OverviewPage from '../components/admin/pages/OverviewPage'
import OrdersPage from '../components/admin/pages/OrdersPage'
import ReconciliationPage from '../components/admin/pages/ReconciliationPage'
import AccountsPage from '../components/admin/pages/AccountsPage'
import DecisionsPage from '../components/admin/pages/DecisionsPage'

type Page = 'overview' | 'orders' | 'reconciliation' | 'accounts' | 'decisions'

export default function Home() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [activePage, setActivePage] = useState<Page>('overview')

  function renderPage() {
    if (activePage === 'overview')       return <OverviewPage />
    if (activePage === 'orders')         return <OrdersPage />
    if (activePage === 'reconciliation') return <ReconciliationPage />
    if (activePage === 'accounts')       return <AccountsPage />
    if (activePage === 'decisions')      return <DecisionsPage />
    return null
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
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
