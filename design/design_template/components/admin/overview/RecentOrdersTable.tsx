'use client'

import { Search } from 'lucide-react'
import { useState } from 'react'

const STATUS_STYLES: Record<string, { bg: string; color: string; dot: string }> = {
  filled:    { bg: '#f0fdf4', color: '#16a34a', dot: '#22c55e' },
  pending:   { bg: '#fffbeb', color: '#d97706', dot: '#f59e0b' },
  cancelled: { bg: '#fef2f2', color: '#dc2626', dot: '#ef4444' },
  partial:   { bg: '#eff6ff', color: '#2563eb', dot: '#3b82f6' },
}

const orders = [
  { id: 'ORD-8821', symbol: 'AAPL',  side: 'BUY',  qty: 200,  price: '$182.40', status: 'filled',    broker: 'Alpaca',    time: '09:32:14' },
  { id: 'ORD-8820', symbol: 'TSLA',  side: 'SELL', qty: 50,   price: '$248.70', status: 'filled',    broker: 'IBKR',      time: '09:28:05' },
  { id: 'ORD-8819', symbol: 'NVDA',  side: 'BUY',  qty: 100,  price: '$875.20', status: 'pending',   broker: 'Alpaca',    time: '09:25:41' },
  { id: 'ORD-8818', symbol: 'MSFT',  side: 'BUY',  qty: 75,   price: '$414.90', status: 'partial',   broker: 'TD Amerit.', time: '09:21:33' },
  { id: 'ORD-8817', symbol: 'AMZN',  side: 'SELL', qty: 30,   price: '$190.15', status: 'cancelled', broker: 'IBKR',      time: '09:18:02' },
  { id: 'ORD-8816', symbol: 'GOOGL', side: 'BUY',  qty: 40,   price: '$172.30', status: 'filled',    broker: 'Alpaca',    time: '09:14:55' },
]

export default function RecentOrdersTable() {
  const [search, setSearch] = useState('')

  const filtered = orders.filter(
    (o) =>
      o.symbol.toLowerCase().includes(search.toLowerCase()) ||
      o.id.toLowerCase().includes(search.toLowerCase()) ||
      o.broker.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#e8eaed' }}>
      <div className="flex items-center justify-between px-5 py-3.5 border-b" style={{ borderColor: '#e8eaed' }}>
        <div>
          <h2 className="text-sm font-semibold" style={{ color: '#111827' }}>Recent Orders</h2>
          <p className="text-xs mt-0.5" style={{ color: '#9ca3af' }}>Last 24 hours</p>
        </div>
        <div
          className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-xs"
          style={{ backgroundColor: '#f9fafb', borderColor: '#e8eaed' }}
        >
          <Search size={12} style={{ color: '#9ca3af' }} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search orders…"
            className="bg-transparent outline-none w-32 text-xs placeholder-gray-400"
            style={{ color: '#374151' }}
          />
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
              {['Order ID', 'Symbol', 'Side', 'Qty', 'Price', 'Status', 'Broker', 'Time'].map((h) => (
                <th key={h} className="px-5 py-2.5 text-left text-xs font-medium whitespace-nowrap" style={{ color: '#9ca3af' }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((o) => {
              const s = STATUS_STYLES[o.status]
              return (
                <tr
                  key={o.id}
                  className="transition-colors"
                  style={{ borderBottom: '1px solid #f9fafb' }}
                  onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.backgroundColor = '#f9fafb')}
                  onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.backgroundColor = '')}
                >
                  <td className="px-5 py-3 text-xs font-mono" style={{ color: '#6b7280' }}>{o.id}</td>
                  <td className="px-5 py-3 text-xs font-semibold" style={{ color: '#111827' }}>{o.symbol}</td>
                  <td className="px-5 py-3 text-xs font-semibold" style={{ color: o.side === 'BUY' ? '#16a34a' : '#dc2626' }}>{o.side}</td>
                  <td className="px-5 py-3 text-xs tabular-nums" style={{ color: '#374151' }}>{o.qty}</td>
                  <td className="px-5 py-3 text-xs tabular-nums font-medium" style={{ color: '#111827' }}>{o.price}</td>
                  <td className="px-5 py-3">
                    <span
                      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                      style={{ backgroundColor: s.bg, color: s.color }}
                    >
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: s.dot }} />
                      {o.status.charAt(0).toUpperCase() + o.status.slice(1)}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-xs" style={{ color: '#6b7280' }}>{o.broker}</td>
                  <td className="px-5 py-3 text-xs font-mono" style={{ color: '#9ca3af' }}>{o.time}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
