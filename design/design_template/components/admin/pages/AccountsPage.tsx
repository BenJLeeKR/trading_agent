'use client'

import { useState } from 'react'
import { Wallet, TrendingUp, TrendingDown, Lock, CheckCircle } from 'lucide-react'

interface Position {
  symbol: string; qty: number; avgCost: string; currentPrice: string; marketValue: string; pnl: string; pnlPct: string; up: boolean
}

interface Account {
  id: string; name: string; broker: string; status: 'active' | 'locked' | 'inactive'
  cash: string; totalValue: string; dayPnl: string; dayPnlUp: boolean
  positions: Position[]
}

const ACCOUNTS: Account[] = [
  {
    id: 'ACC-0041', name: 'Momentum Alpha', broker: 'Alpaca', status: 'active',
    cash: '$48,210.50', totalValue: '$312,450.80', dayPnl: '+$4,210.30', dayPnlUp: true,
    positions: [
      { symbol: 'AAPL',  qty: 200, avgCost: '$178.20', currentPrice: '$182.40', marketValue: '$36,480', pnl: '+$840',   pnlPct: '+2.36%', up: true  },
      { symbol: 'NVDA',  qty: 100, avgCost: '$820.00', currentPrice: '$875.20', marketValue: '$87,520', pnl: '+$5,520', pnlPct: '+6.73%', up: true  },
      { symbol: 'GOOGL', qty:  40, avgCost: '$175.50', currentPrice: '$172.30', marketValue: '$6,892',  pnl: '−$128',   pnlPct: '−1.82%', up: false },
      { symbol: 'AMD',   qty: 150, avgCost: '$158.00', currentPrice: '$155.40', marketValue: '$23,310', pnl: '−$390',   pnlPct: '−1.65%', up: false },
    ],
  },
  {
    id: 'ACC-0042', name: 'Mean Reversion', broker: 'IBKR', status: 'locked',
    cash: '$12,480.00', totalValue: '$198,630.40', dayPnl: '−$1,820.50', dayPnlUp: false,
    positions: [
      { symbol: 'TSLA',  qty:  50, avgCost: '$255.00', currentPrice: '$248.70', marketValue: '$12,435', pnl: '−$315',   pnlPct: '−2.47%', up: false },
      { symbol: 'JPM',   qty:  80, avgCost: '$190.00', currentPrice: '$196.20', marketValue: '$15,696', pnl: '+$496',   pnlPct: '+3.26%', up: true  },
      { symbol: 'META',  qty:  60, avgCost: '$488.00', currentPrice: '$492.10', marketValue: '$29,526', pnl: '+$246',   pnlPct: '+0.84%', up: true  },
    ],
  },
  {
    id: 'ACC-0043', name: 'Arbitrage Fund', broker: 'TD Amerit.', status: 'active',
    cash: '$65,300.00', totalValue: '$241,890.20', dayPnl: '+$2,100.00', dayPnlUp: true,
    positions: [
      { symbol: 'MSFT',  qty:  75, avgCost: '$410.00', currentPrice: '$414.90', marketValue: '$31,118', pnl: '+$368',   pnlPct: '+1.19%', up: true  },
      { symbol: 'NFLX',  qty:  25, avgCost: '$630.00', currentPrice: '$625.80', marketValue: '$15,645', pnl: '−$105',   pnlPct: '−0.67%', up: false },
    ],
  },
  {
    id: 'ACC-0044', name: 'Trend Following', broker: 'IBKR', status: 'active',
    cash: '$82,100.00', totalValue: '$156,700.00', dayPnl: '+$980.00', dayPnlUp: true,
    positions: [
      { symbol: 'META',  qty:  60, avgCost: '$480.00', currentPrice: '$492.10', marketValue: '$29,526', pnl: '+$726',   pnlPct: '+2.52%', up: true  },
      { symbol: 'AMZN',  qty:  30, avgCost: '$192.00', currentPrice: '$190.15', marketValue: '$5,705',  pnl: '−$56',    pnlPct: '−0.96%', up: false },
    ],
  },
]

const STATUS_STYLE: Record<string, { bg: string; color: string; dot: string }> = {
  active:   { bg: '#f0fdf4', color: '#16a34a', dot: '#22c55e' },
  locked:   { bg: '#fef2f2', color: '#dc2626', dot: '#ef4444' },
  inactive: { bg: '#f3f4f6', color: '#6b7280', dot: '#9ca3af' },
}

function AccountStatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLE[status]
  const Icon = status === 'locked' ? Lock : CheckCircle
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium" style={{ backgroundColor: s.bg, color: s.color }}>
      <Icon size={10} />
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  )
}

export default function AccountsPage() {
  const [selected, setSelected] = useState<Account>(ACCOUNTS[0])

  return (
    <div className="flex gap-4 h-full min-h-0">
      {/* Accounts list */}
      <div className="flex flex-col gap-2 shrink-0 overflow-y-auto" style={{ width: 248 }}>
        <p className="text-xs font-semibold px-1" style={{ color: '#9ca3af' }}>ACCOUNTS ({ACCOUNTS.length})</p>
        {ACCOUNTS.map((acc) => {
          const isActive = selected.id === acc.id
          const s = STATUS_STYLE[acc.status]
          return (
            <button
              key={acc.id}
              onClick={() => setSelected(acc)}
              className="w-full text-left p-3 rounded-xl border transition-colors"
              style={{
                backgroundColor: isActive ? '#f0f4ff' : '#fff',
                borderColor: isActive ? '#bfdbfe' : '#e8eaed',
              }}
            >
              <div className="flex items-start justify-between mb-1.5">
                <div>
                  <p className="text-xs font-semibold" style={{ color: '#111827' }}>{acc.name}</p>
                  <p className="text-[10px] font-mono mt-0.5" style={{ color: '#9ca3af' }}>{acc.id}</p>
                </div>
                <AccountStatusBadge status={acc.status} />
              </div>
              <div className="flex items-center justify-between mt-2">
                <div>
                  <p className="text-[10px]" style={{ color: '#9ca3af' }}>Total Value</p>
                  <p className="text-xs font-semibold tabular-nums" style={{ color: '#111827' }}>{acc.totalValue}</p>
                </div>
                <div className="text-right">
                  <p className="text-[10px]" style={{ color: '#9ca3af' }}>Day P&L</p>
                  <p className="text-xs font-semibold tabular-nums" style={{ color: acc.dayPnlUp ? '#16a34a' : '#dc2626' }}>{acc.dayPnl}</p>
                </div>
              </div>
              <p className="text-[10px] mt-1.5" style={{ color: '#9ca3af' }}>{acc.broker}</p>
            </button>
          )
        })}
      </div>

      {/* Account detail */}
      <div className="flex-1 flex flex-col gap-4 min-w-0">
        {/* Locked warning */}
        {selected.status === 'locked' && (
          <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border" style={{ backgroundColor: '#fef2f2', borderColor: '#fca5a5' }}>
            <Lock size={14} style={{ color: '#dc2626' }} />
            <p className="text-xs font-semibold" style={{ color: '#dc2626' }}>
              This account is locked — trading is suspended pending reconciliation review.
            </p>
          </div>
        )}

        {/* Summary cards */}
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: 'Total Value', value: selected.totalValue, sub: 'Market + Cash' },
            { label: 'Cash Balance', value: selected.cash, sub: 'Available' },
            { label: 'Day P&L', value: selected.dayPnl, sub: 'Today', up: selected.dayPnlUp },
          ].map((card) => (
            <div key={card.label} className="bg-white rounded-xl border p-4" style={{ borderColor: '#e8eaed' }}>
              <p className="text-xs" style={{ color: '#9ca3af' }}>{card.label}</p>
              <p
                className="text-xl font-bold tabular-nums mt-1"
                style={{ color: 'up' in card ? (card.up ? '#16a34a' : '#dc2626') : '#111827' }}
              >
                {card.value}
              </p>
              <div className="flex items-center gap-1 mt-1">
                {'up' in card && card.up !== undefined
                  ? card.up
                    ? <TrendingUp size={11} style={{ color: '#16a34a' }} />
                    : <TrendingDown size={11} style={{ color: '#dc2626' }} />
                  : null}
                <p className="text-xs" style={{ color: '#9ca3af' }}>{card.sub}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Positions table */}
        <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#e8eaed' }}>
          <div className="flex items-center justify-between px-5 py-3 border-b" style={{ borderColor: '#e8eaed' }}>
            <div className="flex items-center gap-2">
              <Wallet size={13} style={{ color: '#374151' }} />
              <p className="text-xs font-semibold" style={{ color: '#111827' }}>Positions — {selected.name}</p>
            </div>
            <p className="text-xs" style={{ color: '#9ca3af' }}>{selected.positions.length} positions</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
                  {['Symbol', 'Qty', 'Avg Cost', 'Current Price', 'Market Value', 'P&L', 'P&L %'].map((h) => (
                    <th key={h} className="px-5 py-2.5 text-left text-xs font-medium whitespace-nowrap" style={{ color: '#9ca3af' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {selected.positions.map((pos) => (
                  <tr
                    key={pos.symbol}
                    className="transition-colors"
                    style={{ borderBottom: '1px solid #f9fafb' }}
                    onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.backgroundColor = '#f9fafb')}
                    onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.backgroundColor = '')}
                  >
                    <td className="px-5 py-3 text-xs font-semibold" style={{ color: '#111827' }}>{pos.symbol}</td>
                    <td className="px-5 py-3 text-xs tabular-nums" style={{ color: '#374151' }}>{pos.qty}</td>
                    <td className="px-5 py-3 text-xs tabular-nums" style={{ color: '#6b7280' }}>{pos.avgCost}</td>
                    <td className="px-5 py-3 text-xs tabular-nums font-medium" style={{ color: '#111827' }}>{pos.currentPrice}</td>
                    <td className="px-5 py-3 text-xs tabular-nums font-medium" style={{ color: '#374151' }}>{pos.marketValue}</td>
                    <td className="px-5 py-3 text-xs tabular-nums font-semibold" style={{ color: pos.up ? '#16a34a' : '#dc2626' }}>
                      {pos.pnl}
                    </td>
                    <td className="px-5 py-3">
                      <span
                        className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full"
                        style={{ backgroundColor: pos.up ? '#f0fdf4' : '#fef2f2', color: pos.up ? '#16a34a' : '#dc2626' }}
                      >
                        {pos.up ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                        {pos.pnlPct}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
