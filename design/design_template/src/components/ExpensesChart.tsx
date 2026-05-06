import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts"
import { ChevronDown } from "lucide-react"

const data = [
  { month: "Jan", value: 1200 },
  { month: "Feb", value: 1800 },
  { month: "Mar", value: 2200 },
  { month: "Apr", value: 1600 },
  { month: "May", value: 2800 },
  { month: "Jun", value: 4000 },
  { month: "Jul", value: 2400 },
  { month: "Aug", value: 1900 },
  { month: "Sep", value: 2100 },
  { month: "Oct", value: 1700 },
  { month: "Nov", value: 2300 },
  { month: "Dec", value: 2000 },
]

export function ExpensesChart() {
  return (
    <div className="rounded-xl bg-white p-5 shadow-sm border border-[#e2e8f0]">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-base font-semibold text-[#0f172a]">Expenses by Year</h3>
        <button className="flex items-center gap-1 text-sm text-[#64748b] hover:text-[#0f172a] transition-colors">
          Last Year
          <ChevronDown className="h-4 w-4" />
        </button>
      </div>
      <div className="h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} barSize={24}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
            <XAxis
              dataKey="month"
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#94a3b8", fontSize: 12 }}
            />
            <YAxis
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#94a3b8", fontSize: 12 }}
              tickFormatter={(value) => `${value / 1000}k`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1e293b",
                border: "none",
                borderRadius: "8px",
                color: "#fff",
              }}
              formatter={(value: number) => [`$${value.toLocaleString()}`, "Expenses"]}
              cursor={{ fill: "rgba(37, 99, 235, 0.1)" }}
            />
            <Bar dataKey="value" radius={[4, 4, 0, 0]}>
              {data.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={entry.month === "Jun" ? "#2563eb" : "#e2e8f0"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
