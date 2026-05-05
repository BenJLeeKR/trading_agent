'use client'

import { AlertTriangle, Lock, RefreshCcw, Activity, CheckCircle } from 'lucide-react'

const alerts = [
  {
    icon: Lock,
    color: '#dc2626',
    bg: '#fef2f2',
    border: '#fca5a5',
    title: 'Active Lock',
    desc: 'Account ACC-0042 is locked during reconciliation.',
    time: '2m ago',
  },
  {
    icon: RefreshCcw,
    color: '#d97706',
    bg: '#fffbeb',
    border: '#fcd34d',
    title: 'Reconciliation Required',
    desc: 'RUN-2291 has 3 unmatched positions.',
    time: '14m ago',
  },
  {
    icon: AlertTriangle,
    color: '#d97706',
    bg: '#fffbeb',
    border: '#fcd34d',
    title: 'Degraded Health',
    desc: 'Broker feed latency exceeded 500ms threshold.',
    time: '31m ago',
  },
]

const systemStatus = [
  { label: 'Order Router',      ok: true },
  { label: 'Broker Feed',       ok: false },
  { label: 'Recon Engine',      ok: true },
  { label: 'Decision Engine',   ok: true },
]

export default function AlertsPanel() {
  return (
    <div
      className="flex flex-col gap-3 shrink-0 overflow-y-auto"
      style={{ width: 272 }}
    >
      {/* System status */}
      <div className="bg-white rounded-xl border p-4" style={{ borderColor: '#e8eaed' }}>
        <p className="text-xs font-semibold mb-3" style={{ color: '#111827' }}>System Health</p>
        <div className="flex flex-col gap-2">
          {systemStatus.map((s) => (
            <div key={s.label} className="flex items-center justify-between">
              <span className="text-xs" style={{ color: '#6b7280' }}>{s.label}</span>
              <div className="flex items-center gap-1.5">
                {s.ok
                  ? <CheckCircle size={12} style={{ color: '#22c55e' }} />
                  : <AlertTriangle size={12} style={{ color: '#f59e0b' }} />
                }
                <span className="text-xs font-medium" style={{ color: s.ok ? '#16a34a' : '#d97706' }}>
                  {s.ok ? 'Operational' : 'Degraded'}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Active alerts */}
      <div className="bg-white rounded-xl border p-4" style={{ borderColor: '#e8eaed' }}>
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs font-semibold" style={{ color: '#111827' }}>Active Alerts</p>
          <div className="flex items-center gap-1">
            <Activity size={11} style={{ color: '#ef4444' }} />
            <span className="text-[10px] font-semibold" style={{ color: '#ef4444' }}>{alerts.length}</span>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          {alerts.map((a) => {
            const Icon = a.icon
            return (
              <div
                key={a.title}
                className="flex gap-2.5 p-2.5 rounded-lg border"
                style={{ backgroundColor: a.bg, borderColor: a.border }}
              >
                <Icon size={14} className="shrink-0 mt-0.5" style={{ color: a.color }} />
                <div className="min-w-0">
                  <p className="text-xs font-semibold" style={{ color: a.color }}>{a.title}</p>
                  <p className="text-[11px] mt-0.5 leading-relaxed" style={{ color: '#6b7280' }}>{a.desc}</p>
                  <p className="text-[10px] mt-1" style={{ color: '#9ca3af' }}>{a.time}</p>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
