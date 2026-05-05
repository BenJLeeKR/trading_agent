'use client'

import {
  LayoutDashboard,
  ClipboardList,
  GitCompareArrows,
  Wallet,
  Brain,
  ChevronLeft,
  Bot,
  Activity,
} from 'lucide-react'

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
  activePage: string
  onNavigate: (page: string) => void
}

const mainNav = [
  { id: 'overview', icon: LayoutDashboard, label: 'Overview' },
  { id: 'orders', icon: ClipboardList, label: 'Orders' },
  { id: 'reconciliation', icon: GitCompareArrows, label: 'Reconciliation' },
  { id: 'accounts', icon: Wallet, label: 'Accounts' },
  { id: 'decisions', icon: Brain, label: 'Decisions' },
]

export default function Sidebar({ collapsed, onToggle, activePage, onNavigate }: SidebarProps) {
  return (
    <aside
      className="relative flex flex-col h-full border-r shrink-0 transition-all duration-200"
      style={{
        width: collapsed ? 56 : 212,
        backgroundColor: '#ffffff',
        borderColor: '#e8eaed',
      }}
    >
      {/* Logo */}
      <div
        className="flex items-center gap-2.5 px-3 py-4 border-b shrink-0"
        style={{ borderColor: '#e8eaed' }}
      >
        <div
          className="flex items-center justify-center w-8 h-8 rounded-lg shrink-0"
          style={{ backgroundColor: '#1d2939' }}
        >
          <Bot size={15} color="#ffffff" />
        </div>
        {!collapsed && (
          <div>
            <span className="font-semibold text-sm tracking-tight" style={{ color: '#111827' }}>
              AgentTrade
            </span>
            <div className="flex items-center gap-1 mt-0.5">
              <Activity size={9} style={{ color: '#10b981' }} />
              <span className="text-[10px]" style={{ color: '#10b981' }}>
                Live
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Collapse toggle */}
      <button
        onClick={onToggle}
        className="absolute -right-3 top-14 z-10 flex items-center justify-center w-6 h-6 rounded-full border shadow-sm transition-colors"
        style={{ backgroundColor: '#ffffff', borderColor: '#e8eaed', color: '#9ca3af' }}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.color = '#374151')}
        onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.color = '#9ca3af')}
      >
        <ChevronLeft
          size={11}
          style={{
            transform: collapsed ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s',
          }}
        />
      </button>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-3 flex flex-col gap-0.5 px-2">
        {!collapsed && (
          <p
            className="px-2 pt-1 pb-2 text-[10px] font-semibold uppercase tracking-widest"
            style={{ color: '#9ca3af' }}
          >
            Navigation
          </p>
        )}
        {collapsed && <div className="mt-2" />}

        {mainNav.map((item) => {
          const Icon = item.icon
          const isActive = activePage === item.id
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              title={collapsed ? item.label : undefined}
              className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-sm transition-colors w-full text-left"
              style={{
                backgroundColor: isActive ? '#f0f4ff' : 'transparent',
                color: isActive ? '#3b82f6' : '#6b7280',
                fontWeight: isActive ? 500 : 400,
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  const el = e.currentTarget as HTMLElement
                  el.style.backgroundColor = '#f9fafb'
                  el.style.color = '#374151'
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  const el = e.currentTarget as HTMLElement
                  el.style.backgroundColor = 'transparent'
                  el.style.color = '#6b7280'
                }
              }}
            >
              <Icon size={16} className="shrink-0" />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </button>
          )
        })}
      </nav>

      {/* System status */}
      {!collapsed && (
        <div className="px-3 py-3 border-t shrink-0" style={{ borderColor: '#e8eaed' }}>
          <div
            className="flex items-center gap-2 px-2.5 py-2 rounded-lg"
            style={{ backgroundColor: '#f0fdf4' }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full shrink-0"
              style={{ backgroundColor: '#10b981' }}
            />
            <div className="overflow-hidden">
              <p className="text-[11px] font-medium truncate" style={{ color: '#065f46' }}>
                All systems normal
              </p>
              <p className="text-[10px] truncate" style={{ color: '#6b7280' }}>
                Last sync 2m ago
              </p>
            </div>
          </div>
        </div>
      )}
      {collapsed && (
        <div className="flex justify-center py-3 border-t shrink-0" style={{ borderColor: '#e8eaed' }}>
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#10b981' }} />
        </div>
      )}
    </aside>
  )
}
