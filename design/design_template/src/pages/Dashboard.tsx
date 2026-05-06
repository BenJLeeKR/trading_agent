import { Sidebar } from "@/components/Sidebar"
import { Header } from "@/components/Header"
import { SummaryCard } from "@/components/SummaryCard"
import { ExpensesChart } from "@/components/ExpensesChart"
import { TotalTrips } from "@/components/TotalTrips"
import { TripsChart } from "@/components/TripsChart"
import { TrackingDelivery } from "@/components/TrackingDelivery"

// Donut chart SVG component
function DonutChart({ percentage, color }: { percentage: number; color: string }) {
  const radius = 24
  const circumference = 2 * Math.PI * radius
  const strokeDashoffset = circumference - (percentage / 100) * circumference

  return (
    <svg width="70" height="70" viewBox="0 0 70 70">
      <circle
        cx="35"
        cy="35"
        r={radius}
        fill="none"
        stroke="#e2e8f0"
        strokeWidth="8"
      />
      <circle
        cx="35"
        cy="35"
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth="8"
        strokeDasharray={circumference}
        strokeDashoffset={strokeDashoffset}
        strokeLinecap="round"
        transform="rotate(-90 35 35)"
      />
    </svg>
  )
}

// Wave chart SVG component
function WaveChart() {
  return (
    <svg width="70" height="50" viewBox="0 0 70 50">
      <path
        d="M0 40 Q15 35, 25 30 T50 25 T70 15"
        fill="none"
        stroke="#f97316"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <circle cx="70" cy="15" r="4" fill="#f97316" />
    </svg>
  )
}

export function Dashboard() {
  return (
    <div className="flex h-screen bg-[#f8fafc]">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header />
        <main className="flex-1 overflow-auto p-6">
          <div className="grid grid-cols-12 gap-6">
            {/* Summary Cards */}
            <div className="col-span-8">
              <div className="grid grid-cols-3 gap-4 mb-6">
                <SummaryCard
                  title="Total Expenses"
                  subtitle="Thai Baht"
                  value="$ 27,200"
                  change="+44% ↑"
                  changeType="positive"
                  icon={<DonutChart percentage={44} color="#2563eb" />}
                />
                <SummaryCard
                  title="Total Salaries"
                  subtitle="Thai Baht"
                  value="$ 12,100"
                  change="-20% ↓"
                  changeType="negative"
                  icon={<WaveChart />}
                />
                <SummaryCard
                  title="Total Wage's"
                  subtitle="Thai Baht"
                  value="$ 15,100"
                  change="+56% ↑"
                  changeType="positive"
                  icon={<DonutChart percentage={56} color="#10b981" />}
                />
              </div>

              {/* Expenses Chart */}
              <div className="mb-6">
                <ExpensesChart />
              </div>

              {/* Bottom row */}
              <div className="grid grid-cols-2 gap-4">
                <TotalTrips />
                <TripsChart />
              </div>
            </div>

            {/* Tracking Delivery */}
            <div className="col-span-4">
              <TrackingDelivery />
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
