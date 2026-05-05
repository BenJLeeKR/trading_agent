import StatCards from '../components/overview/StatCards'
import SalesChart from '../components/overview/SalesChart'
import TransactionsTable from '../components/overview/TransactionsTable'
import CongratulationsPanel from '../components/overview/CongratulationsPanel'

export default function OverviewPage() {
  return (
    <div className="flex flex-col gap-5">
      {/* Stat cards */}
      <StatCards />

      {/* Chart + Congratulations side by side */}
      <div className="flex gap-5">
        <SalesChart />
        <CongratulationsPanel />
      </div>

      {/* Transactions table */}
      <TransactionsTable />
    </div>
  )
}
