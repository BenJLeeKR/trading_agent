'use client'

import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AdminShell } from '@/components/admin/admin-shell'
import { OverviewDashboard } from '@/components/admin/overview-dashboard'
import { OrdersView } from '@/components/admin/orders-view'
import { ReconciliationView } from '@/components/admin/reconciliation-view'
import { AccountsView } from '@/components/admin/accounts-view'
import { DecisionsView } from '@/components/admin/decisions-view'
import { PlaceholderView } from '@/components/admin/placeholder-view'

export default function App() {
  return (
    <BrowserRouter basename="/admin">
      <AdminShell>
        <Routes>
          <Route path="/" element={<OverviewDashboard />} />
          <Route path="/orders" element={<OrdersView />} />
          <Route path="/reconciliation" element={<ReconciliationView />} />
          <Route path="/accounts" element={<AccountsView />} />
          <Route path="/decisions" element={<DecisionsView />} />
          <Route path="/logs" element={<PlaceholderView title="Logs" description="System and agent logs will appear here." />} />
          <Route path="/settings" element={<PlaceholderView title="System Settings" description="Read-only system configuration." />} />
        </Routes>
      </AdminShell>
    </BrowserRouter>
  )
}
