'use client'

import { useState } from 'react'
import { Search, ChevronDown, X, Clock, CheckCircle, XCircle, Minus } from 'lucide-react'

const STATUS_STYLES: Record<string, { bg: string; color: string; dot: string; Icon: React.ElementType }> = {
  filled:    { bg: '#f0fdf4', color: '#16a34a', dot: '#22c55e', Icon: CheckCircle },
  pending:   { bg: '#fffbeb', color: '#d97706', dot: '#f59e0b', Icon: Clock },
  cancelled: { bg: '#fef2f2', color: '#dc2626', dot: '#ef4444', Icon: XCircle },
  partial:   { bg: '#eff6ff', color: '#2563eb', dot: '#3b82f6', Icon: Minus },
}

interface Order {
  id: string; symbol: string; side: 'BUY' | 'SELL'; qty: number; filled: number
  price: string; avgFill: string; status: string; broker: string
  account: string; strategy: string; time: string; date: string
}

const ALL_ORDERS: Order[] = [
  { id: 'ORD-8821', symbol: 'AAPL',  side: 'BUY',  qty: 200, filled: 200, price: '$182.40', avgFill: '$182.38', status: 'filled',    broker: 'Alpaca',      account: 'ACC-0041', strategy: 'MomentumV2',  time: '09:32:14', date: '2024-05-05' },
  { id: 'ORD-8820', symbol: 'TSLA',  side: 'SELL', qty: 50,  filled: 50,  price: '$248.70', avgFill: '$248.65', status: 'filled',    broker: 'IBKR',        account: 'ACC-0042', strategy: 'MeanRevV1',   time: '09:28:05', date: '2024-05-05' },
  { id: 'ORD-8819', symbol: 'NVDA',  side: 'BUY',  qty: 100, filled: 0,   price: '$875.20', avgFill: '—',       status: 'pending',   broker: 'Alpaca',      account: 'ACC-0041', strategy: 'MomentumV2',  time: '09:25:41', date: '2024-05-05' },
  { id: 'ORD-8818', symbol: 'MSFT',  side: 'BUY',  qty: 75,  filled: 40,  price: '$414.90', avgFill: '$414.88', status: 'partial',   broker: 'TD Amerit.',  account: 'ACC-0043', strategy: 'ArbitrageX',  time: '09:21:33', date: '2024-05-05' },
  { id: 'ORD-8817', symbol: 'AMZN',  side: 'SELL', qty: 30,  filled: 0,   price: '$190.15', avgFill: '—',       status: 'cancelled', broker: 'IBKR',        account: 'ACC-0042', strategy: 'MeanRevV1',   time: '09:18:02', date: '2024-05-05' },
  { id: 'ORD-8816', symbol: 'GOOGL', side: 'BUY',  qty: 40,  filled: 40,  price: '$172.30', avgFill: '$172.29', status: 'filled',    broker: 'Alpaca',      account: 'ACC-0041', strategy: 'MomentumV2',  time: '09:14:55', date: '2024-05-05' },
  { id: 'ORD-8815', symbol: 'META',  side: 'BUY',  qty: 60,  filled: 60,  price: '$492.10', avgFill: '$492.07', status: 'filled',    broker: 'IBKR',        account: 'ACC-0044', strategy: 'TrendFol.',   time: '09:10:22', date: '2024-05-05' },
  { id: 'ORD-8814', symbol: 'NFLX',  side: 'SELL', qty: 25,  filled: 0,   price: '$625.80', avgFill: '—',       status: 'pending',   broker: 'TD Amerit.',  account: 'ACC-0043', strategy: 'ArbitrageX',  time: '09:05:11', date: '2024-05-05' },
  { id: 'ORD-8813', symbol: 'AMD',   side: 'BUY',  qty: 150, filled: 150, price: '$155.40', avgFill: '$155.39', status: 'filled',    broker: 'Alpaca',      account: 'ACC-0041', strategy: 'MomentumV2',  time: '08:58:44', date: '2024-05-05' },
  { id: 'ORD-8812', symbol: 'JPM',   side: 'SELL', qty: 80,  filled: 80,  price: '$196.20', avgFill: '$196.18', status: 'filled',    broker: 'IBKR',        account: 'ACC-0042', strategy: 'MeanRevV1',   time: '08:51:30', date: '2024-05-05' },
]

const STATUS_FILTERS = ['all', 'filled', 'pending', 'partial', 'cancelled']
const BROKERS = ['All Brokers', 'Alpaca', 'IBKR', 'TD Amerit.']

function DetailRow({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5" style={{ borderBottom: '1px solid #f9fafb' }}>
      <span className="text-xs shrink-0" style={{ color: '#9ca3af' }}>{label}</span>
      <span className="text-xs font-medium text-right" style={{ color: valueColor ?? '#111827' }}>{value}</span>
    </div>
  )
}

export default function OrdersPage() {
  const [search, setSearch]     = useState('')
  const [status, setStatus]     = useState('all')
  const [broker, setBroker]     = useState('All Brokers')
  const [selected, setSelected] = useState<Order | null>(null)

  const filtered = ALL_ORDERS.filter((o) => {
    const q = search.toLowerCase()
    const matchSearch = o.symbol.toLowerCase().includes(q) || o.id.toLowerCase().includes(q) || o.account.toLowerCase().includes(q)
    const matchStatus = status === 'all' || o.status === status
    const matchBroker = broker === 'All Brokers' || o.broker === broker
    return matchSearch && matchStatus && matchBroker
  })

  return (
    <div className="flex gap-4 h-full min-h-0">
      {/* Left: filter bar + table */}
      <div className="flex-1 flex flex-col gap-3 min-w-0">
        {/* Filter bar */}
        <div className="bg-white rounded-xl border p-3 flex items-center gap-2 flex-wrap" style={{ borderColor: '#e8eaed' }}>
          <div
            className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg border flex-1 min-w-40"
            style={{ backgroundColor: '#f9fafb', borderColor: '#e8eaed' }}
          >
            <Search size={12} style={{ color: '#9ca3af' }} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by symbol, order ID, account…"
              className="bg-transparent outline-none w-full text-xs"
              style={{ color: '#374151' }}
            />
            {search && (
              <button onClick={() => setSearch('')}><X size={11} style={{ color: '#9ca3af' }} /></button>
            )}
          </div>

          <div className="flex items-center gap-1">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f}
                onClick={() => setStatus(f)}
                className="px-2.5 py-1 rounded-lg text-xs font-medium capitalize transition-colors"
                style={{ backgroundColor: status === f ? '#1d2939' : '#f3f4f6', color: status === f ? '#fff' : '#6b7280' }}
              >
                {f}
              </button>
            ))}
          </div>

          <div
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-xs"
            style={{ backgroundColor: '#f9fafb', borderColor: '#e8eaed' }}
          >
            <select
              value={broker}
              onChange={(e) => setBroker(e.target.value)}
              className="bg-transparent outline-none text-xs cursor-pointer"
              style={{ color: '#374151' }}
            >
              {BROKERS.map((b) => <option key={b}>{b}</option>)}
            </select>
            <ChevronDown size={11} style={{ color: '#9ca3af' }} />
          </div>
        </div>

        {/* Table */}
        <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#e8eaed' }}>
          <div className="flex items-center justify-between px-5 py-3 border-b" style={{ borderColor: '#e8eaed' }}>
            <p className="text-xs font-semibold" style={{ color: '#111827' }}>{filtered.length} orders</p>
            <p className="text-xs" style={{ color: '#9ca3af' }}>Today, May 5 2024</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
                  {['Order ID', 'Symbol', 'Side', 'Qty', 'Filled', 'Price', 'Avg Fill', 'Status', 'Broker', 'Account', 'Time'].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left text-xs font-medium whitespace-nowrap" style={{ color: '#9ca3af' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((o) => {
                  const s = STATUS_STYLES[o.status]
                  const isActive = selected?.id === o.id
                  return (
                    <tr
                      key={o.id}
                      onClick={() => setSelected(isActive ? null : o)}
                      className="cursor-pointer transition-colors"
                      style={{ borderBottom: '1px solid #f9fafb', backgroundColor: isActive ? '#f0f4ff' : '' }}
                      onMouseEnter={(e) => { if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = '#f9fafb' }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = isActive ? '#f0f4ff' : '' }}
                    >
                      <td className="px-4 py-2.5 text-xs font-mono" style={{ color: '#6b7280' }}>{o.id}</td>
                      <td className="px-4 py-2.5 text-xs font-semibold" style={{ color: '#111827' }}>{o.symbol}</td>
                      <td className="px-4 py-2.5 text-xs font-semibold" style={{ color: o.side === 'BUY' ? '#16a34a' : '#dc2626' }}>{o.side}</td>
                      <td className="px-4 py-2.5 text-xs tabular-nums" style={{ color: '#374151' }}>{o.qty}</td>
                      <td className="px-4 py-2.5 text-xs tabular-nums" style={{ color: '#374151' }}>{o.filled}</td>
                      <td className="px-4 py-2.5 text-xs tabular-nums font-medium" style={{ color: '#111827' }}>{o.price}</td>
                      <td className="px-4 py-2.5 text-xs tabular-nums" style={{ color: '#6b7280' }}>{o.avgFill}</td>
                      <td className="px-4 py-2.5">
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium" style={{ backgroundColor: s.bg, color: s.color }}>
                          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: s.dot }} />
                          {o.status.charAt(0).toUpperCase() + o.status.slice(1)}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-xs" style={{ color: '#6b7280' }}>{o.broker}</td>
                      <td className="px-4 py-2.5 text-xs font-mono" style={{ color: '#6b7280' }}>{o.account}</td>
                      <td className="px-4 py-2.5 text-xs font-mono" style={{ color: '#9ca3af' }}>{o.time}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Right: detail panel */}
      {selected && (
        <div className="shrink-0 flex flex-col gap-3 overflow-y-auto" style={{ width: 280 }}>
          {/* Order detail */}
          <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#e8eaed' }}>
            <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: '#e8eaed' }}>
              <p className="text-xs font-semibold" style={{ color: '#111827' }}>Order Detail</p>
              <button onClick={() => setSelected(null)} style={{ color: '#9ca3af' }}>
                <X size={13} />
              </button>
            </div>
            {/* Status banner */}
            <div className="px-4 py-2.5 border-b" style={{ backgroundColor: STATUS_STYLES[selected.status].bg, borderColor: '#e8eaed' }}>
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: STATUS_STYLES[selected.status].dot }} />
                <span className="text-xs font-semibold capitalize" style={{ color: STATUS_STYLES[selected.status].color }}>{selected.status}</span>
              </div>
            </div>
            <div className="px-4 py-3">
              <DetailRow label="Order ID"    value={selected.id} />
              <DetailRow label="Symbol"      value={selected.symbol} />
              <DetailRow label="Side"        value={selected.side} valueColor={selected.side === 'BUY' ? '#16a34a' : '#dc2626'} />
              <DetailRow label="Quantity"    value={String(selected.qty)} />
              <DetailRow label="Filled"      value={String(selected.filled)} />
              <DetailRow label="Order Price" value={selected.price} />
              <DetailRow label="Avg Fill"    value={selected.avgFill} />
              <DetailRow label="Broker"      value={selected.broker} />
              <DetailRow label="Account"     value={selected.account} />
              <DetailRow label="Strategy"    value={selected.strategy} />
              <DetailRow label="Date"        value={selected.date} />
              <DetailRow label="Time"        value={selected.time} />
            </div>
          </div>

          {/* State events */}
          <div className="bg-white rounded-xl border p-4" style={{ borderColor: '#e8eaed' }}>
            <p className="text-xs font-semibold mb-3" style={{ color: '#111827' }}>State Events</p>
            {[
              { label: 'Order Created',   color: '#3b82f6' },
              { label: 'Sent to Broker',  color: '#8b5cf6' },
              ...(selected.status !== 'cancelled'
                ? [{ label: 'Acknowledged', color: '#10b981' }]
                : [{ label: 'Cancelled',    color: '#ef4444' }]),
              ...(selected.status === 'filled' || selected.status === 'partial'
                ? [{ label: 'Fill Received', color: '#10b981' }]
                : []),
            ].map((ev, i, arr) => (
              <div key={i} className="flex gap-2.5">
                <div className="flex flex-col items-center">
                  <span className="w-2 h-2 rounded-full mt-0.5 shrink-0" style={{ backgroundColor: ev.color }} />
                  {i < arr.length - 1 && <span className="w-px flex-1 my-1" style={{ backgroundColor: '#e8eaed' }} />}
                </div>
                <div className="pb-2.5">
                  <p className="text-xs font-medium" style={{ color: '#374151' }}>{ev.label}</p>
                  <p className="text-[10px]" style={{ color: '#9ca3af' }}>{selected.time}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Broker mapping */}
          <div className="bg-white rounded-xl border p-4" style={{ borderColor: '#e8eaed' }}>
            <p className="text-xs font-semibold mb-2" style={{ color: '#111827' }}>Broker Mapping</p>
            <DetailRow label="Broker"       value={selected.broker} />
            <DetailRow label="Ext Order ID" value={`EXT-${selected.id.replace('ORD-', '')}`} />
            <DetailRow label="Routing"      value="Direct" />
            <DetailRow label="Commission"   value="$0.005/share" />
          </div>
        </div>
      )}
    </div>
  )
}
