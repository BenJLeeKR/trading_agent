import { useState } from 'react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { ChevronDown, TrendingUp } from 'lucide-react'

const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const chartData = [
  { month: 'Jan', transactions: 120, products: 80 },
  { month: 'Feb', transactions: 180, products: 110 },
  { month: 'Mar', transactions: 140, products: 90 },
  { month: 'Apr', transactions: 200, products: 130 },
  { month: 'May', transactions: 160, products: 100 },
  { month: 'Jun', transactions: 190, products: 140 },
  { month: 'Jul', transactions: 210, products: 150 },
  { month: 'Aug', transactions: 222, products: 44 },
  { month: 'Sep', transactions: 170, products: 120 },
  { month: 'Oct', transactions: 185, products: 115 },
  { month: 'Nov', transactions: 195, products: 135 },
  { month: 'Dec', transactions: 230, products: 160 },
]

const timeFilters = ['1d', '7d', '30d', '16m', 'Max']

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-gray-900 text-white rounded-xl shadow-lg px-4 py-3 text-xs">
        <p className="font-semibold mb-1.5 text-gray-200">{label} 2023</p>
        {payload.map((entry: any) => (
          <div key={entry.dataKey} className="flex items-center gap-2 mb-0.5">
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ backgroundColor: entry.color }}
            />
            <span className="text-gray-300 capitalize">{entry.dataKey}:</span>
            <span className="font-semibold">{entry.value}</span>
          </div>
        ))}
      </div>
    )
  }
  return null
}

export default function SalesChart() {
  const [activeFilter, setActiveFilter] = useState('7d')
  const [activeMonth, setActiveMonth] = useState('Aug')

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 flex-1">
      <div className="flex items-start justify-between mb-4">
        <div>
          <p className="text-xs text-gray-400 mb-0.5">Your sales report</p>
          <p className="text-xs text-gray-300">Look at your sale</p>
          <div className="mt-3">
            <p className="text-3xl font-bold text-gray-900">$4,435.70</p>
            <div className="flex items-center gap-1.5 mt-1">
              <TrendingUp size={12} className="text-emerald-500" />
              <span className="text-xs text-emerald-500 font-medium">$2,330.00 (+2.5%)</span>
            </div>
          </div>
        </div>
        <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-600 hover:bg-gray-50 transition-colors">
          Total Sales
          <ChevronDown size={13} />
        </button>
      </div>

      {/* Chart */}
      <div className="h-44">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 5, right: 5, left: -30, bottom: 0 }}>
            <defs>
              <linearGradient id="txGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.15} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="prodGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.15} />
                <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f1f3" vertical={false} />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 10, fill: '#9ca3af' }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: '#9ca3af' }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ stroke: '#e5e7eb', strokeWidth: 1 }} />
            <Area
              type="monotone"
              dataKey="transactions"
              stroke="#3b82f6"
              strokeWidth={2}
              fill="url(#txGradient)"
              dot={false}
              activeDot={{ r: 4, fill: '#3b82f6', strokeWidth: 0 }}
            />
            <Area
              type="monotone"
              dataKey="products"
              stroke="#f59e0b"
              strokeWidth={2}
              fill="url(#prodGradient)"
              dot={false}
              activeDot={{ r: 4, fill: '#f59e0b', strokeWidth: 0 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Time filter + month labels */}
      <div className="flex items-center justify-between mt-3">
        {/* Period filters */}
        <div className="flex items-center gap-1">
          {timeFilters.map((f) => (
            <button
              key={f}
              onClick={() => setActiveFilter(f)}
              className="px-2.5 py-1 rounded-lg text-xs font-medium transition-colors"
              style={{
                backgroundColor: activeFilter === f ? '#3b82f6' : 'transparent',
                color: activeFilter === f ? '#fff' : '#6b7280',
              }}
            >
              {f}
            </button>
          ))}
        </div>

        {/* Month labels */}
        <div className="flex items-center gap-3">
          {months.map((m) => (
            <button
              key={m}
              onClick={() => setActiveMonth(m)}
              className="text-xs transition-colors"
              style={{
                color: activeMonth === m ? '#3b82f6' : '#9ca3af',
                fontWeight: activeMonth === m ? 600 : 400,
              }}
            >
              {m}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
