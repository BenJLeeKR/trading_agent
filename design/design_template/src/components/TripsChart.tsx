import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts"
import { ChevronDown } from "lucide-react"

const data = [
  { month: "Jan", value: 40 },
  { month: "Feb", value: 45 },
  { month: "Mar", value: 55 },
  { month: "Apr", value: 75 },
  { month: "May", value: 60 },
  { month: "Jan", value: 50 },
  { month: "Jul", value: 45 },
  { month: "Aug", value: 40 },
]

export function TripsChart() {
  return (
    <div className="rounded-xl bg-white p-5 shadow-sm border border-[#e2e8f0]">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-semibold text-[#0f172a]">Trips by Year</h3>
        <button className="flex items-center gap-1 text-sm text-[#64748b] hover:text-[#0f172a] transition-colors">
          Last Year
          <ChevronDown className="h-4 w-4" />
        </button>
      </div>
      <div className="h-[180px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <defs>
              <linearGradient id="colorTrips" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#2563eb" stopOpacity={0.15} />
                <stop offset="95%" stopColor="#2563eb" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
            <XAxis
              dataKey="month"
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#94a3b8", fontSize: 11 }}
            />
            <YAxis
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              tickFormatter={(value) => `${value}%`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1e293b",
                border: "none",
                borderRadius: "8px",
                color: "#fff",
              }}
              formatter={(value: number) => [`${value}%`, "Trips"]}
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke="#2563eb"
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#colorTrips)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
