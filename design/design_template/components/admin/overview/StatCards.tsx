'use client'

import { ClipboardList, GitCompareArrows, Wallet, Brain, TrendingUp, TrendingDown } from 'lucide-react'
import type { ElementType } from 'react'

interface StatCardProps {
  icon: ElementType
  iconBg: string
  iconColor: string
  label: string
  value: string | number
  change: string
  changeUp: boolean | null
  alert?: boolean
}

function StatCard({ icon: Icon, iconBg, iconColor, label, value, change, changeUp, alert }: StatCardProps) {
  return (
    <div
      className="flex-1 bg-white rounded-xl border p-4 flex flex-col gap-3"
      style={{ borderColor: alert ? '#fcd34d' : '#e8eaed' }}
    >
      <div className="flex items-center justify-between">
        <div
          className="flex items-center justify-center w-9 h-9 rounded-lg shrink-0"
          style={{ backgroundColor: iconBg }}
        >
          <Icon size={16} style={{ color: iconColor }} />
        </div>
        {alert && (
          <span
            className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
            style={{ backgroundColor: '#fffbeb', color: '#d97706' }}
          >
            Needs attention
          </span>
        )}
      </div>
      <div>
        <p className="text-2xl font-bold tracking-tight" style={{ color: '#111827' }}>{value}</p>
        <p className="text-xs mt-0.5" style={{ color: '#6b7280' }}>{label}</p>
      </div>
      <div className="flex items-center gap-1">
        {changeUp === true  && <TrendingUp  size={11} style={{ color: '#10b981' }} />}
        {changeUp === false && <TrendingDown size={11} style={{ color: '#ef4444' }} />}
        <span
          className="text-xs font-medium"
          style={{ color: changeUp === true ? '#10b981' : changeUp === false ? '#ef4444' : '#9ca3af' }}
        >
          {change}
        </span>
        {changeUp !== null && (
          <span className="text-xs" style={{ color: '#9ca3af' }}>&nbsp;vs last 7d</span>
        )}
      </div>
    </div>
  )
}

export default function StatCards() {
  const stats: StatCardProps[] = [
    {
      icon: ClipboardList,
      iconBg: '#eff6ff',
      iconColor: '#3b82f6',
      label: 'Total Orders',
      value: '2,847',
      change: '+12.4%',
      changeUp: true,
    },
    {
      icon: GitCompareArrows,
      iconBg: '#fffbeb',
      iconColor: '#f59e0b',
      label: 'Pending Reconciliation',
      value: '34',
      change: '+3 today',
      changeUp: false,
      alert: true,
    },
    {
      icon: Wallet,
      iconBg: '#f0fdf4',
      iconColor: '#10b981',
      label: 'Active Accounts',
      value: '18',
      change: 'No change',
      changeUp: null,
    },
    {
      icon: Brain,
      iconBg: '#f5f3ff',
      iconColor: '#8b5cf6',
      label: 'Open Decisions',
      value: '126',
      change: '-8.2%',
      changeUp: true,
    },
  ]

  return (
    <div className="flex gap-4">
      {stats.map((s) => (
        <StatCard key={s.label} {...s} />
      ))}
    </div>
  )
}
