'use client'

import { useState } from 'react'
import { Lock, AlertTriangle, CheckCircle, RefreshCcw, X, ChevronDown } from 'lucide-react'

const RUN_STATUS: Record<string, { bg: string; color: string; dot: string }> = {
  completed:  { bg: '#f0fdf4', color: '#16a34a', dot: '#22c55e' },
  running:    { bg: '#eff6ff', color: '#2563eb', dot: '#3b82f6' },
  failed:     { bg: '#fef2f2', color: '#dc2626', dot: '#ef4444' },
  pending:    { bg: '#fffbeb', color: '#d97706', dot: '#f59e0b' },
}

interface Run {
  id: string; account: string; date: string; time: string
  status: string; matched: number; unmatched: number; duration: string
}

interface Lock {
  id: string; account: string; reason: string; lockedAt: string; lockedBy: string; severity: 'critical' | 'warning'
}

const RUNS: Run[] = [
  { id: 'RUN-2295', account: 'ACC-0041', date: '2024-05-05', time: '08:00:02', status: 'completed', matched: 142, unmatched: 0,  duration: '4.2s' },
  { id: 'RUN-2294', account: 'ACC-0042', date: '2024-05-05', time: '08:00:01', status: 'failed',    matched: 88,  unmatched: 5,  duration: '6.8s' },
  { id: 'RUN-2293', account: 'ACC-0043', date: '2024-05-05', time: '07:59:58', status: 'completed', matched: 67,  unmatched: 0,  duration: '3.1s' },
  { id: 'RUN-2292', account: 'ACC-0044', date: '2024-05-05', time: '07:59:55', status: 'running',   matched: 31,  unmatched: 0,  duration: '—'    },
  { id: 'RUN-2291', account: 'ACC-0042', date: '2024-05-04', time: '08:00:03', status: 'failed',    matched: 102, unmatched: 3,  duration: '5.5s' },
  { id: 'RUN-2290', account: 'ACC-0041', date: '2024-05-04', time: '08:00:01', status: 'completed', matched: 139, unmatched: 0,  duration: '4.0s' },
  { id: 'RUN-2289', account: 'ACC-0043', date: '2024-05-04', time: '07:59:59', status: 'completed', matched: 64,  unmatched: 0,  duration: '2.9s' },
  { id: 'RUN-2288', account: 'ACC-0044', date: '2024-05-04', time: '07:59:57', status: 'pending',   matched: 0,   unmatched: 0,  duration: '—'    },
]

const LOCKS: Lock[] = [
  { id: 'LCK-0014', account: 'ACC-0042', reason: 'Unmatched positions from RUN-2294', lockedAt: '08:01:12', lockedBy: 'ReconEngine', severity: 'critical' },
  { id: 'LCK-0013', account: 'ACC-0042', reason: 'Unmatched positions from RUN-2291', lockedAt: '08:02:40', lockedBy: 'ReconEngine', severity: 'warning' },
]

const UNMATCHED = [
  { runId: 'RUN-2294', symbol: 'TSLA', expected: 50,   actual: 45,   diff: -5,  type: 'position' },
  { runId: 'RUN-2294', symbol: 'META', expected: 60,   actual: 60,   diff: 0,   type: 'cash'     },
  { runId: 'RUN-2294', symbol: 'NFLX', expected: 25,   actual: 22,   diff: -3,  type: 'position' },
  { runId: 'RUN-2291', symbol: 'JPM',  expected: 80,   actual: 77,   diff: -3,  type: 'position' },
  { runId: 'RUN-2291', symbol: 'AMZN', expected: 30,   actual: 28,   diff: -2,  type: 'position' },
  { runId: 'RUN-2291', symbol: 'AAPL', expected: 200,  actual: 198,  diff: -2,  type: 'position' },
]

function StatusBadge({ status }: { status: string }) {
  const s = RUN_STATUS[status] ?? RUN_STATUS['pending']
  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium" style={{ backgroundColor: s.bg, color: s.color }}>
      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: s.dot }} />
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  )
}

export default function ReconciliationPage() {
  const [selectedRun, setSelectedRun] = useState<Run | null>(null)
  const [statusFilter, setStatusFilter] = useState('all')

  const filteredRuns = RUNS.filter((r) => statusFilter === 'all' || r.status === statusFilter)
  const activeLocks = LOCKS.filter((l) => l.severity === 'critical')

  return (
    <div className="flex flex-col gap-4">
      {/* Active lock warning banner */}
      {activeLocks.length > 0 && (
        <div
          className="flex items-start gap-3 px-4 py-3 rounded-xl border"
          style={{ backgroundColor: '#fef2f2', borderColor: '#fca5a5' }}
        >
          <Lock size={15} className="shrink-0 mt-0.5" style={{ color: '#dc2626' }} />
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold" style={{ color: '#dc2626' }}>
              {activeLocks.length} Active Lock{activeLocks.length > 1 ? 's' : ''} — Trading suspended on affected accounts
            </p>
            <p className="text-xs mt-0.5" style={{ color: '#6b7280' }}>
              {activeLocks.map((l) => `${l.account} (${l.reason})`).join(' · ')}
            </p>
          </div>
          <span className="text-xs font-medium shrink-0 px-2.5 py-1 rounded-lg border cursor-pointer" style={{ backgroundColor: '#fff', borderColor: '#fca5a5', color: '#dc2626' }}>
            Review Locks
          </span>
        </div>
      )}

      <div className="flex gap-4 min-h-0">
        {/* Left column: runs + unmatched */}
        <div className="flex-1 flex flex-col gap-4 min-w-0">
          {/* Runs table */}
          <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#e8eaed' }}>
            <div className="flex items-center justify-between px-5 py-3 border-b" style={{ borderColor: '#e8eaed' }}>
              <div>
                <p className="text-xs font-semibold" style={{ color: '#111827' }}>Reconciliation Runs</p>
                <p className="text-xs mt-0.5" style={{ color: '#9ca3af' }}>Last 48 hours</p>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1">
                  {['all', 'completed', 'failed', 'running', 'pending'].map((f) => (
                    <button
                      key={f}
                      onClick={() => setStatusFilter(f)}
                      className="px-2 py-0.5 rounded-lg text-xs font-medium capitalize transition-colors"
                      style={{ backgroundColor: statusFilter === f ? '#1d2939' : '#f3f4f6', color: statusFilter === f ? '#fff' : '#6b7280' }}
                    >
                      {f}
                    </button>
                  ))}
                </div>
                <button className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs transition-colors" style={{ borderColor: '#e8eaed', color: '#6b7280' }}>
                  <RefreshCcw size={11} />
                  Re-run
                </button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
                    {['Run ID', 'Account', 'Date', 'Time', 'Status', 'Matched', 'Unmatched', 'Duration'].map((h) => (
                      <th key={h} className="px-4 py-2.5 text-left text-xs font-medium whitespace-nowrap" style={{ color: '#9ca3af' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredRuns.map((r) => {
                    const isActive = selectedRun?.id === r.id
                    return (
                      <tr
                        key={r.id}
                        onClick={() => setSelectedRun(isActive ? null : r)}
                        className="cursor-pointer transition-colors"
                        style={{ borderBottom: '1px solid #f9fafb', backgroundColor: isActive ? '#f0f4ff' : '' }}
                        onMouseEnter={(e) => { if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = '#f9fafb' }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = isActive ? '#f0f4ff' : '' }}
                      >
                        <td className="px-4 py-2.5 text-xs font-mono" style={{ color: '#6b7280' }}>{r.id}</td>
                        <td className="px-4 py-2.5 text-xs font-mono" style={{ color: '#374151' }}>{r.account}</td>
                        <td className="px-4 py-2.5 text-xs" style={{ color: '#6b7280' }}>{r.date}</td>
                        <td className="px-4 py-2.5 text-xs font-mono" style={{ color: '#9ca3af' }}>{r.time}</td>
                        <td className="px-4 py-2.5"><StatusBadge status={r.status} /></td>
                        <td className="px-4 py-2.5 text-xs tabular-nums font-medium" style={{ color: '#16a34a' }}>{r.matched}</td>
                        <td className="px-4 py-2.5 text-xs tabular-nums font-medium" style={{ color: r.unmatched > 0 ? '#dc2626' : '#9ca3af' }}>
                          {r.unmatched > 0 ? r.unmatched : '—'}
                        </td>
                        <td className="px-4 py-2.5 text-xs font-mono" style={{ color: '#9ca3af' }}>{r.duration}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Unmatched positions */}
          <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#e8eaed' }}>
            <div className="flex items-center justify-between px-5 py-3 border-b" style={{ borderColor: '#e8eaed' }}>
              <div className="flex items-center gap-2">
                <AlertTriangle size={13} style={{ color: '#f59e0b' }} />
                <p className="text-xs font-semibold" style={{ color: '#111827' }}>Unmatched Positions</p>
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full" style={{ backgroundColor: '#fef2f2', color: '#dc2626' }}>
                  {UNMATCHED.length}
                </span>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
                    {['Run ID', 'Symbol', 'Type', 'Expected', 'Actual', 'Diff'].map((h) => (
                      <th key={h} className="px-4 py-2.5 text-left text-xs font-medium" style={{ color: '#9ca3af' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {UNMATCHED.map((u, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid #f9fafb', backgroundColor: u.diff !== 0 ? '#fffbeb' : '' }}>
                      <td className="px-4 py-2.5 text-xs font-mono" style={{ color: '#6b7280' }}>{u.runId}</td>
                      <td className="px-4 py-2.5 text-xs font-semibold" style={{ color: '#111827' }}>{u.symbol}</td>
                      <td className="px-4 py-2.5">
                        <span className="text-xs px-1.5 py-0.5 rounded" style={{ backgroundColor: '#f3f4f6', color: '#6b7280' }}>{u.type}</span>
                      </td>
                      <td className="px-4 py-2.5 text-xs tabular-nums" style={{ color: '#374151' }}>{u.expected}</td>
                      <td className="px-4 py-2.5 text-xs tabular-nums" style={{ color: '#374151' }}>{u.actual}</td>
                      <td className="px-4 py-2.5 text-xs tabular-nums font-semibold" style={{ color: u.diff < 0 ? '#dc2626' : '#16a34a' }}>
                        {u.diff < 0 ? u.diff : `+${u.diff}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Right column: locks panel */}
        <div className="flex flex-col gap-3 shrink-0" style={{ width: 272 }}>
          <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#e8eaed' }}>
            <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: '#e8eaed' }}>
              <div className="flex items-center gap-2">
                <Lock size={13} style={{ color: '#374151' }} />
                <p className="text-xs font-semibold" style={{ color: '#111827' }}>Account Locks</p>
              </div>
              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full" style={{ backgroundColor: '#fef2f2', color: '#dc2626' }}>
                {LOCKS.length} active
              </span>
            </div>
            <div className="flex flex-col gap-0 divide-y" style={{ borderColor: '#f3f4f6' }}>
              {LOCKS.map((lock) => (
                <div key={lock.id} className="px-4 py-3">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-semibold font-mono" style={{ color: '#111827' }}>{lock.account}</span>
                    <span
                      className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                      style={lock.severity === 'critical'
                        ? { backgroundColor: '#fef2f2', color: '#dc2626' }
                        : { backgroundColor: '#fffbeb', color: '#d97706' }}
                    >
                      {lock.severity}
                    </span>
                  </div>
                  <p className="text-xs leading-relaxed mb-2" style={{ color: '#6b7280' }}>{lock.reason}</p>
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px]" style={{ color: '#9ca3af' }}>Locked at</span>
                      <span className="text-[10px] font-mono" style={{ color: '#374151' }}>{lock.lockedAt}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-[10px]" style={{ color: '#9ca3af' }}>Locked by</span>
                      <span className="text-[10px]" style={{ color: '#374151' }}>{lock.lockedBy}</span>
                    </div>
                  </div>
                  <button
                    className="mt-2.5 w-full text-xs font-medium py-1.5 rounded-lg border transition-colors"
                    style={{ borderColor: '#fca5a5', color: '#dc2626', backgroundColor: '#fff' }}
                    onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.backgroundColor = '#fef2f2')}
                    onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.backgroundColor = '#fff')}
                  >
                    Release Lock
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Run detail panel */}
          {selectedRun && (
            <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#e8eaed' }}>
              <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: '#e8eaed' }}>
                <p className="text-xs font-semibold" style={{ color: '#111827' }}>Run Detail</p>
                <button onClick={() => setSelectedRun(null)} style={{ color: '#9ca3af' }}>
                  <X size={13} />
                </button>
              </div>
              <div className="px-4 py-3 flex flex-col gap-0">
                {[
                  ['Run ID',    selectedRun.id],
                  ['Account',   selectedRun.account],
                  ['Date',      selectedRun.date],
                  ['Time',      selectedRun.time],
                  ['Status',    selectedRun.status],
                  ['Matched',   String(selectedRun.matched)],
                  ['Unmatched', String(selectedRun.unmatched)],
                  ['Duration',  selectedRun.duration],
                ].map(([label, val]) => (
                  <div key={label} className="flex items-center justify-between py-1.5" style={{ borderBottom: '1px solid #f9fafb' }}>
                    <span className="text-xs" style={{ color: '#9ca3af' }}>{label}</span>
                    <span className="text-xs font-medium" style={{ color: label === 'Unmatched' && Number(val) > 0 ? '#dc2626' : '#111827' }}>{val}</span>
                  </div>
                ))}
              </div>
              {selectedRun.unmatched > 0 && (
                <div className="px-4 py-3 border-t" style={{ borderColor: '#e8eaed', backgroundColor: '#fffbeb' }}>
                  <div className="flex items-center gap-2">
                    <AlertTriangle size={12} style={{ color: '#d97706' }} />
                    <p className="text-xs" style={{ color: '#d97706' }}>
                      {selectedRun.unmatched} unmatched position{selectedRun.unmatched > 1 ? 's' : ''} require review.
                    </p>
                  </div>
                </div>
              )}
              {selectedRun.status === 'completed' && selectedRun.unmatched === 0 && (
                <div className="px-4 py-3 border-t" style={{ borderColor: '#e8eaed', backgroundColor: '#f0fdf4' }}>
                  <div className="flex items-center gap-2">
                    <CheckCircle size={12} style={{ color: '#16a34a' }} />
                    <p className="text-xs" style={{ color: '#16a34a' }}>All positions matched successfully.</p>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
