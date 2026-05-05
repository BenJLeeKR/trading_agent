'use client'

import { useState } from 'react'
import { X, TrendingUp, TrendingDown, Brain } from 'lucide-react'

type Action = 'BUY' | 'SELL' | 'HOLD'
type Outcome = 'executed' | 'rejected' | 'pending' | 'overridden'

interface Signal {
  name: string; value: string; direction: 'positive' | 'negative' | 'neutral'
}

interface Decision {
  id: string; symbol: string; action: Action; confidence: number
  strategy: string; account: string; reason: string
  outcome: Outcome; time: string; date: string
  signals: Signal[]
  context: { marketRegime: string; volatility: string; volume: string; spread: string }
}

const OUTCOME_STYLE: Record<Outcome, { bg: string; color: string; dot: string }> = {
  executed:   { bg: '#f0fdf4', color: '#16a34a', dot: '#22c55e' },
  rejected:   { bg: '#fef2f2', color: '#dc2626', dot: '#ef4444' },
  pending:    { bg: '#fffbeb', color: '#d97706', dot: '#f59e0b' },
  overridden: { bg: '#f5f3ff', color: '#7c3aed', dot: '#8b5cf6' },
}

const ACTION_COLOR: Record<Action, string> = { BUY: '#16a34a', SELL: '#dc2626', HOLD: '#6b7280' }

const DECISIONS: Decision[] = [
  {
    id: 'DEC-5841', symbol: 'AAPL', action: 'BUY', confidence: 87, strategy: 'MomentumV2',
    account: 'ACC-0041', reason: 'Strong upward momentum detected. RSI breakout above 62. Volume 2.1x average.',
    outcome: 'executed', time: '09:32:10', date: '2024-05-05',
    signals: [
      { name: 'RSI (14)',     value: '63.2',  direction: 'positive' },
      { name: 'MACD Signal',  value: '+0.42', direction: 'positive' },
      { name: 'Volume Ratio', value: '2.1x',  direction: 'positive' },
      { name: 'ATR',          value: '$2.80', direction: 'neutral'  },
    ],
    context: { marketRegime: 'Trending', volatility: 'Low', volume: 'High', spread: '$0.01' },
  },
  {
    id: 'DEC-5840', symbol: 'TSLA', action: 'SELL', confidence: 74, strategy: 'MeanRevV1',
    account: 'ACC-0042', reason: 'Overbought conditions. RSI at 78. Price exceeded upper Bollinger Band.',
    outcome: 'executed', time: '09:28:01', date: '2024-05-05',
    signals: [
      { name: 'RSI (14)',        value: '78.1',  direction: 'negative' },
      { name: 'BB Upper',        value: '$251.2', direction: 'negative' },
      { name: 'MACD Signal',     value: '−0.18', direction: 'negative' },
      { name: 'Volume Ratio',    value: '1.4x',  direction: 'neutral'  },
    ],
    context: { marketRegime: 'Mean Reverting', volatility: 'Medium', volume: 'Medium', spread: '$0.05' },
  },
  {
    id: 'DEC-5839', symbol: 'NVDA', action: 'BUY', confidence: 91, strategy: 'MomentumV2',
    account: 'ACC-0041', reason: 'AI sector momentum. Breakout from 3-week consolidation. High institutional flow.',
    outcome: 'pending', time: '09:25:38', date: '2024-05-05',
    signals: [
      { name: 'RSI (14)',     value: '68.5',  direction: 'positive' },
      { name: 'MACD Signal',  value: '+1.20', direction: 'positive' },
      { name: 'Volume Ratio', value: '3.4x',  direction: 'positive' },
      { name: 'ATR',          value: '$12.4', direction: 'neutral'  },
    ],
    context: { marketRegime: 'Trending', volatility: 'High', volume: 'Very High', spread: '$0.10' },
  },
  {
    id: 'DEC-5838', symbol: 'AMZN', action: 'SELL', confidence: 58, strategy: 'MeanRevV1',
    account: 'ACC-0042', reason: 'Moderate reversal signal. Confidence below threshold — order rejected by risk filter.',
    outcome: 'rejected', time: '09:18:00', date: '2024-05-05',
    signals: [
      { name: 'RSI (14)',     value: '71.0',  direction: 'negative' },
      { name: 'MACD Signal',  value: '−0.08', direction: 'negative' },
      { name: 'Volume Ratio', value: '0.9x',  direction: 'neutral'  },
      { name: 'ATR',          value: '$3.20', direction: 'neutral'  },
    ],
    context: { marketRegime: 'Choppy', volatility: 'Medium', volume: 'Low', spread: '$0.02' },
  },
  {
    id: 'DEC-5837', symbol: 'MSFT', action: 'HOLD', confidence: 62, strategy: 'ArbitrageX',
    account: 'ACC-0043', reason: 'Insufficient spread for arbitrage. Holding current position.',
    outcome: 'executed', time: '09:21:30', date: '2024-05-05',
    signals: [
      { name: 'RSI (14)',     value: '55.2', direction: 'neutral'  },
      { name: 'Spread',       value: '$0.05', direction: 'neutral' },
      { name: 'Volume Ratio', value: '1.1x', direction: 'neutral'  },
      { name: 'ATR',          value: '$4.10', direction: 'neutral' },
    ],
    context: { marketRegime: 'Range-bound', volatility: 'Low', volume: 'Medium', spread: '$0.05' },
  },
  {
    id: 'DEC-5836', symbol: 'META', action: 'BUY', confidence: 79, strategy: 'TrendFol.',
    account: 'ACC-0044', reason: 'Trend continuation confirmed. 50-day MA crossover. Positive sector sentiment.',
    outcome: 'overridden', time: '09:10:18', date: '2024-05-05',
    signals: [
      { name: 'RSI (14)',     value: '61.0',  direction: 'positive' },
      { name: 'MA Cross',     value: 'Bull',  direction: 'positive' },
      { name: 'Volume Ratio', value: '1.8x',  direction: 'positive' },
      { name: 'ATR',          value: '$8.60', direction: 'neutral'  },
    ],
    context: { marketRegime: 'Trending', volatility: 'Medium', volume: 'High', spread: '$0.03' },
  },
]

function ConfidenceBar({ value }: { value: number }) {
  const color = value >= 80 ? '#22c55e' : value >= 65 ? '#f59e0b' : '#ef4444'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: '#f3f4f6' }}>
        <div className="h-full rounded-full transition-all" style={{ width: `${value}%`, backgroundColor: color }} />
      </div>
      <span className="text-xs font-semibold tabular-nums shrink-0" style={{ color, minWidth: 32 }}>{value}%</span>
    </div>
  )
}

const SIGNAL_DIR_COLOR: Record<string, string> = { positive: '#16a34a', negative: '#dc2626', neutral: '#6b7280' }

export default function DecisionsPage() {
  const [selected, setSelected] = useState<Decision | null>(null)
  const [outcomeFilter, setOutcomeFilter] = useState<'all' | Outcome>('all')
  const [actionFilter, setActionFilter]   = useState<'all' | Action>('all')

  const filtered = DECISIONS.filter((d) => {
    const matchOutcome = outcomeFilter === 'all' || d.outcome === outcomeFilter
    const matchAction  = actionFilter  === 'all' || d.action  === actionFilter
    return matchOutcome && matchAction
  })

  return (
    <div className="flex gap-4 h-full min-h-0">
      {/* Left: filters + decisions table */}
      <div className="flex-1 flex flex-col gap-3 min-w-0">
        {/* Filter bar */}
        <div className="bg-white rounded-xl border p-3 flex items-center gap-3 flex-wrap" style={{ borderColor: '#e8eaed' }}>
          <div className="flex items-center gap-1">
            <span className="text-xs mr-1" style={{ color: '#9ca3af' }}>Outcome</span>
            {(['all', 'executed', 'rejected', 'pending', 'overridden'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setOutcomeFilter(f)}
                className="px-2 py-0.5 rounded-lg text-xs font-medium capitalize transition-colors"
                style={{ backgroundColor: outcomeFilter === f ? '#1d2939' : '#f3f4f6', color: outcomeFilter === f ? '#fff' : '#6b7280' }}
              >
                {f}
              </button>
            ))}
          </div>
          <div className="w-px h-4 shrink-0" style={{ backgroundColor: '#e8eaed' }} />
          <div className="flex items-center gap-1">
            <span className="text-xs mr-1" style={{ color: '#9ca3af' }}>Action</span>
            {(['all', 'BUY', 'SELL', 'HOLD'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setActionFilter(f)}
                className="px-2 py-0.5 rounded-lg text-xs font-medium transition-colors"
                style={{ backgroundColor: actionFilter === f ? '#1d2939' : '#f3f4f6', color: actionFilter === f ? '#fff' : '#6b7280' }}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        {/* Table */}
        <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#e8eaed' }}>
          <div className="flex items-center justify-between px-5 py-3 border-b" style={{ borderColor: '#e8eaed' }}>
            <div className="flex items-center gap-2">
              <Brain size={13} style={{ color: '#374151' }} />
              <p className="text-xs font-semibold" style={{ color: '#111827' }}>Decision Log</p>
            </div>
            <p className="text-xs" style={{ color: '#9ca3af' }}>{filtered.length} decisions</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
                  {['Decision ID', 'Symbol', 'Action', 'Confidence', 'Strategy', 'Account', 'Outcome', 'Time'].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left text-xs font-medium whitespace-nowrap" style={{ color: '#9ca3af' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((d) => {
                  const os = OUTCOME_STYLE[d.outcome]
                  const isActive = selected?.id === d.id
                  return (
                    <tr
                      key={d.id}
                      onClick={() => setSelected(isActive ? null : d)}
                      className="cursor-pointer transition-colors"
                      style={{ borderBottom: '1px solid #f9fafb', backgroundColor: isActive ? '#f0f4ff' : '' }}
                      onMouseEnter={(e) => { if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = '#f9fafb' }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = isActive ? '#f0f4ff' : '' }}
                    >
                      <td className="px-4 py-2.5 text-xs font-mono" style={{ color: '#6b7280' }}>{d.id}</td>
                      <td className="px-4 py-2.5 text-xs font-semibold" style={{ color: '#111827' }}>{d.symbol}</td>
                      <td className="px-4 py-2.5 text-xs font-semibold" style={{ color: ACTION_COLOR[d.action] }}>{d.action}</td>
                      <td className="px-4 py-2.5" style={{ minWidth: 140 }}>
                        <ConfidenceBar value={d.confidence} />
                      </td>
                      <td className="px-4 py-2.5 text-xs" style={{ color: '#6b7280' }}>{d.strategy}</td>
                      <td className="px-4 py-2.5 text-xs font-mono" style={{ color: '#6b7280' }}>{d.account}</td>
                      <td className="px-4 py-2.5">
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium" style={{ backgroundColor: os.bg, color: os.color }}>
                          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: os.dot }} />
                          {d.outcome.charAt(0).toUpperCase() + d.outcome.slice(1)}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-xs font-mono" style={{ color: '#9ca3af' }}>{d.time}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Right: decision detail panel */}
      {selected && (
        <div className="shrink-0 flex flex-col gap-3 overflow-y-auto" style={{ width: 288 }}>
          {/* Decision detail */}
          <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#e8eaed' }}>
            <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: '#e8eaed' }}>
              <p className="text-xs font-semibold" style={{ color: '#111827' }}>Decision Detail</p>
              <button onClick={() => setSelected(null)} style={{ color: '#9ca3af' }}><X size={13} /></button>
            </div>

            {/* Action + outcome banner */}
            <div
              className="px-4 py-3 border-b flex items-center justify-between"
              style={{ backgroundColor: OUTCOME_STYLE[selected.outcome].bg, borderColor: '#e8eaed' }}
            >
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold" style={{ color: ACTION_COLOR[selected.action] }}>{selected.action}</span>
                <span className="text-sm font-semibold" style={{ color: '#111827' }}>{selected.symbol}</span>
              </div>
              <span className="text-xs font-semibold capitalize" style={{ color: OUTCOME_STYLE[selected.outcome].color }}>
                {selected.outcome}
              </span>
            </div>

            {/* Fields */}
            <div className="px-4 py-3 flex flex-col gap-0">
              {[
                ['Decision ID', selected.id],
                ['Strategy',   selected.strategy],
                ['Account',    selected.account],
                ['Date',       selected.date],
                ['Time',       selected.time],
              ].map(([label, val]) => (
                <div key={label} className="flex items-center justify-between py-1.5" style={{ borderBottom: '1px solid #f9fafb' }}>
                  <span className="text-xs" style={{ color: '#9ca3af' }}>{label}</span>
                  <span className="text-xs font-medium" style={{ color: '#111827' }}>{val}</span>
                </div>
              ))}
            </div>

            {/* Confidence */}
            <div className="px-4 pb-3">
              <p className="text-xs mb-1.5" style={{ color: '#9ca3af' }}>Confidence</p>
              <ConfidenceBar value={selected.confidence} />
            </div>

            {/* Reason */}
            <div className="px-4 pb-4 border-t pt-3" style={{ borderColor: '#f3f4f6' }}>
              <p className="text-xs font-medium mb-1" style={{ color: '#374151' }}>Reason</p>
              <p className="text-xs leading-relaxed" style={{ color: '#6b7280' }}>{selected.reason}</p>
            </div>
          </div>

          {/* Signals */}
          <div className="bg-white rounded-xl border p-4" style={{ borderColor: '#e8eaed' }}>
            <p className="text-xs font-semibold mb-3" style={{ color: '#111827' }}>Input Signals</p>
            <div className="flex flex-col gap-0">
              {selected.signals.map((sig) => (
                <div key={sig.name} className="flex items-center justify-between py-1.5" style={{ borderBottom: '1px solid #f9fafb' }}>
                  <span className="text-xs" style={{ color: '#6b7280' }}>{sig.name}</span>
                  <div className="flex items-center gap-1.5">
                    {sig.direction === 'positive' && <TrendingUp  size={10} style={{ color: '#16a34a' }} />}
                    {sig.direction === 'negative' && <TrendingDown size={10} style={{ color: '#dc2626' }} />}
                    <span className="text-xs font-semibold tabular-nums" style={{ color: SIGNAL_DIR_COLOR[sig.direction] }}>
                      {sig.value}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Market context */}
          <div className="bg-white rounded-xl border p-4" style={{ borderColor: '#e8eaed' }}>
            <p className="text-xs font-semibold mb-3" style={{ color: '#111827' }}>Market Context</p>
            <div className="flex flex-col gap-0">
              {Object.entries(selected.context).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between py-1.5" style={{ borderBottom: '1px solid #f9fafb' }}>
                  <span className="text-xs capitalize" style={{ color: '#9ca3af' }}>
                    {k.replace(/([A-Z])/g, ' $1').trim()}
                  </span>
                  <span className="text-xs font-medium" style={{ color: '#374151' }}>{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
