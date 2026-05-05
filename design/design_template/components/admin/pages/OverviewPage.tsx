'use client'

import StatCards from '../overview/StatCards'
import SalesChart from '../overview/SalesChart'
import RecentOrdersTable from '../overview/RecentOrdersTable'
import AlertsPanel from '../overview/AlertsPanel'

export default function OverviewPage() {
  return (
    <div className="flex flex-col gap-4">
      <StatCards />
      <div className="flex gap-4 min-h-0">
        <SalesChart />
        <AlertsPanel />
      </div>
      <RecentOrdersTable />
    </div>
  )
}
