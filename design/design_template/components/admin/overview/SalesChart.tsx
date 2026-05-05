'use client'

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

const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Des']

const chartData = [
  { month: 'Jan', orders: 320, decisions: 210 },
  { month: 'Feb', orders: 480, decisions: 310 },
  { month: 'Mar', orders: 390, decisions: 270 },
  { month: 'Apr', orders: 540, decisions: 380 },
  { month: 'May', orders: 420, decisions: 290 },
  { month: 'Jun', orders: 510, decisions: 360 },
  { month: 'Jul', orders: 580, decisions: 400 },
  { month: 'Aug', orders: 620, decisions: 440 },
  { month: 'Sep', orders: 470, decisions: 320 },
  { month: 'Oct', orders: 530, decisions: 370 },
  { month: 'Nov', orders: 560, decisions: 390 },
  { month: 'Dec', orders: 680, decisions: 480 },
]

const timeFilters = ['1d', '7d', '30d', '16m', 'Max']

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div
        className="rounded-xl shadow-lg px-4 py-3 text-xs"
        style={{ backgroundColor: '#1f2937', color: '#fff' }}
      >
        <p className="font-semibold mb-1.5" style={{ color: '#d1d5db' }}>
          {label} 2023
        </p>
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
          {payload.map((entry: any) => (
          <div key={entry.dataKey} className="flex items-center gap-2 mb-0.5">
            <span
              className="w-1.5 h-1.5 rounded-full shrink-0"
              style={{ backgroundColor: entry.color }}
            />
            <span style={{ color: '#9ca3af' }}>
              {entry.dataKey === 'orders' ? 'Orders' : 'Decisions'}:
            </span>
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
    <div
      className="bg-white rounded-xl border shadow-sm p-5 flex-1 min-w-0"
      style={{ borderColor: '#e8eaed' }}
    >
      {/* Top row */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <p className="text-xs font-semibold" style={{ color: '#374151' }}>Order Volume</p>
          <p className="text-xs mt-0.5" style={{ color: '#9ca3af' }}>Orders vs Decisions — last 12 months</p>
          <div className="mt-3">
            <p className="text-3xl font-bold tabular-nums" style={{ color: '#111827' }}>2,847</p>
            <div className="flex items-center gap-1 mt-1">
              <TrendingUp size={11} style={{ color: '#10b981' }} />
              <span className="text-xs font-medium" style={{ color: '#10b981' }}>
                +12.4% vs last period
              </span>
            </div>
          </div>
        </div>
        <button
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs text-gray-600 hover:bg-gray-50 transition-colors shrink-0"
          style={{ borderColor: '#e8eaed' }}
        >
          All Orders
          <ChevronDown size={12} />
        </button>
      </div>

      {/* Chart */}
      <div style={{ height: 170 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 5, right: 5, left: -30, bottom: 0 }}>
            <defs>
              <linearGradient id="txGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.12} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="prodGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.12} />
                <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" vertical={false} />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 9, fill: '#9ca3af' }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 9, fill: '#9ca3af' }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ stroke: '#e5e7eb', strokeWidth: 1 }} />
            <Area
              type="monotone"
              dataKey="orders"
              stroke="#3b82f6"
              strokeWidth={2}
              fill="url(#txGrad)"
              dot={false}
              activeDot={{ r: 4, fill: '#3b82f6', strokeWidth: 0 }}
            />
            <Area
              type="monotone"
              dataKey="decisions"
              stroke="#8b5cf6"
              strokeWidth={2}
              fill="url(#prodGrad)"
              dot={false}
              activeDot={{ r: 4, fill: '#8b5cf6', strokeWidth: 0 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Time filters row */}
      <div className="flex items-center justify-between mt-3">
        <div className="flex items-center gap-0.5">
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
        <div className="flex items-center gap-3 overflow-x-auto">
          {months.map((m) => (
            <button
              key={m}
              onClick={() => setActiveMonth(m)}
              className="text-xs whitespace-nowrap transition-colors"
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
