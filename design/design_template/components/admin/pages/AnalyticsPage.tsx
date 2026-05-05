'use client'

import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'

const revenueData = [
  { month: 'Jan', revenue: 4200 },
  { month: 'Feb', revenue: 5800 },
  { month: 'Mar', revenue: 4900 },
  { month: 'Apr', revenue: 7200 },
  { month: 'May', revenue: 6100 },
  { month: 'Jun', revenue: 8400 },
  { month: 'Jul', revenue: 7600 },
  { month: 'Aug', revenue: 9100 },
]

const platformData = [
  { name: 'Shopee', orders: 420, revenue: 18200 },
  { name: 'Tokopedia', orders: 310, revenue: 12400 },
  { name: 'Tiktok', orders: 190, revenue: 7800 },
]

const kpis = [
  { label: 'Total Revenue', value: '$61,200', change: '+18.2%', up: true },
  { label: 'Total Orders', value: '920', change: '+12.4%', up: true },
  { label: 'Avg Order Value', value: '$66.5', change: '-2.1%', up: false },
  { label: 'Return Rate', value: '3.2%', change: '-0.4%', up: true },
]

export default function AnalyticsPage() {
  return (
    <div className="flex flex-col gap-5">
      {/* KPI row */}
      <div className="flex gap-4">
        {kpis.map((k) => (
          <div
            key={k.label}
            className="flex-1 bg-white rounded-xl border shadow-sm p-4"
            style={{ borderColor: '#e8eaed' }}
          >
            <p className="text-xs text-gray-400 mb-1">{k.label}</p>
            <p className="text-xl font-bold text-gray-900">{k.value}</p>
            <span
              className="text-xs font-semibold px-1.5 py-0.5 rounded-full mt-1 inline-block"
              style={{
                backgroundColor: k.up ? '#ecfdf5' : '#fef2f2',
                color: k.up ? '#10b981' : '#ef4444',
              }}
            >
              {k.change}
            </span>
          </div>
        ))}
      </div>

      {/* Revenue chart */}
      <div
        className="bg-white rounded-xl border shadow-sm p-5"
        style={{ borderColor: '#e8eaed' }}
      >
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Revenue Over Time</h3>
        <div style={{ height: 200 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={revenueData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.12} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" vertical={false} />
              <XAxis dataKey="month" tick={{ fontSize: 10, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{
                  fontSize: 11,
                  borderRadius: 8,
                  border: '1px solid #e5e7eb',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.06)',
                }}
              />
              <Area type="monotone" dataKey="revenue" stroke="#3b82f6" strokeWidth={2} fill="url(#revGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Platform chart */}
      <div
        className="bg-white rounded-xl border shadow-sm p-5"
        style={{ borderColor: '#e8eaed' }}
      >
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Platform Breakdown</h3>
        <div style={{ height: 180 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={platformData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{
                  fontSize: 11,
                  borderRadius: 8,
                  border: '1px solid #e5e7eb',
                }}
              />
              <Bar dataKey="orders" fill="#3b82f6" radius={[4, 4, 0, 0]} name="Orders" />
              <Bar dataKey="revenue" fill="#10b981" radius={[4, 4, 0, 0]} name="Revenue" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
