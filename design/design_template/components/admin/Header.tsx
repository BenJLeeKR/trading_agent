'use client'

import { Bell, Clock } from 'lucide-react'

const pageMeta: Record<string, { title: string; subtitle: string }> = {
  overview:       { title: 'Overview',        subtitle: 'System summary and recent activity' },
  orders:         { title: 'Orders',           subtitle: 'Browse, filter, and inspect agent orders' },
  reconciliation: { title: 'Reconciliation',   subtitle: 'Run status, lock management, and discrepancies' },
  accounts:       { title: 'Accounts',         subtitle: 'Account positions and cash balances' },
  decisions:      { title: 'Decisions',        subtitle: 'Agent decision log and confidence analysis' },
}

interface HeaderProps {
  activePage: string
}

export default function Header({ activePage }: HeaderProps) {
  const meta = pageMeta[activePage] ?? pageMeta['overview']
  const now = new Date()
  const formatted = now.toLocaleDateString('en-US', {
    day: '2-digit', month: 'short', year: 'numeric',
  })

  return (
    <header
      className="flex items-center justify-between px-6 py-3 bg-white border-b shrink-0"
      style={{ borderColor: '#e8eaed' }}
    >
      <div>
        <h1 className="text-[15px] font-semibold" style={{ color: '#111827' }}>
          {meta.title}
        </h1>
        <p className="text-xs mt-0.5" style={{ color: '#9ca3af' }}>
          {meta.subtitle}
        </p>
      </div>

      <div className="flex items-center gap-2">
        {/* Date/time */}
        <div
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs"
          style={{ backgroundColor: '#f9fafb', borderColor: '#e8eaed', color: '#6b7280' }}
        >
          <Clock size={12} style={{ color: '#9ca3af' }} />
          <span>{formatted}</span>
        </div>

        {/* Notifications */}
        <button
          className="relative flex items-center justify-center w-8 h-8 rounded-lg border transition-colors"
          style={{ backgroundColor: '#f9fafb', borderColor: '#e8eaed', color: '#6b7280' }}
          onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.backgroundColor = '#f3f4f6')}
          onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.backgroundColor = '#f9fafb')}
        >
          <Bell size={15} />
          <span
            className="absolute -top-1 -right-1 flex items-center justify-center w-4 h-4 rounded-full text-white text-[9px] font-bold"
            style={{ backgroundColor: '#ef4444' }}
          >
            3
          </span>
        </button>

        {/* Avatar */}
        <div
          className="flex items-center justify-center w-8 h-8 rounded-full text-white text-xs font-semibold"
          style={{ backgroundColor: '#1d2939' }}
        >
          A
        </div>
      </div>
    </header>
  )
}
