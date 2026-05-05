'use client'

import { Link, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  ShoppingCart,
  Users,
  RefreshCcw,
  ScrollText,
  Settings2,
  Brain,
  ChevronRight,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { label: 'Dashboard', to: '/', icon: LayoutDashboard },
  { label: 'Orders', to: '/orders', icon: ShoppingCart },
  { label: 'Reconciliation', to: '/reconciliation', icon: RefreshCcw },
  { label: 'Accounts', to: '/accounts', icon: Users },
  { label: 'Decisions', to: '/decisions', icon: Brain },
  { label: 'Logs', to: '/logs', icon: ScrollText },
  { label: 'System Settings', to: '/settings', icon: Settings2 },
]

export function AdminShell({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation()

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 flex flex-col border-r border-border bg-sidebar">
        {/* Brand */}
        <div className="flex items-center gap-2.5 px-4 py-4 border-b border-sidebar-border">
          <div className="w-7 h-7 rounded-md bg-primary/20 border border-primary/30 flex items-center justify-center shrink-0">
            <span className="text-primary font-bold text-xs">A</span>
          </div>
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-sidebar-foreground truncate leading-tight">AITrading Co.</p>
            <p className="text-[10px] text-muted-foreground leading-tight">
              Operator Console{' '}
              <span className="text-status-error-fg font-medium">· READ ONLY</span>
            </p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-3 overflow-y-auto" aria-label="Main navigation">
          <ul className="space-y-0.5 px-2">
            {navItems.map(({ label, to, icon: Icon }) => {
              const active = to === '/' ? pathname === '/' : pathname.startsWith(to)
              return (
                <li key={to}>
                  <Link
                    to={to}
                    className={cn(
                      'flex items-center gap-2.5 px-2.5 py-2 rounded-md text-[13px] transition-colors group',
                      active
                        ? 'bg-sidebar-accent text-sidebar-foreground font-medium'
                        : 'text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-foreground'
                    )}
                  >
                    <Icon
                      size={15}
                      className={cn(
                        'shrink-0',
                        active ? 'text-primary' : 'text-muted-foreground group-hover:text-sidebar-foreground'
                      )}
                    />
                    <span className="flex-1 truncate">{label}</span>
                    {active && <ChevronRight size={12} className="text-primary/60 shrink-0" />}
                  </Link>
                </li>
              )
            })}
          </ul>
        </nav>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-sidebar-border">
          <p className="text-[10px] text-muted-foreground/50 tabular-nums">v2.4.1 — build 20230211</p>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top header */}
        <header className="shrink-0 flex items-center justify-between px-5 py-3 border-b border-border bg-card/40">
          <PageTitle pathname={pathname} />
          <div className="flex items-center gap-4">
            {/* Search */}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-surface-2 border border-border text-muted-foreground text-[12px] w-52">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />
              </svg>
              <span>Search...</span>
            </div>
            {/* User */}
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-full bg-primary/20 border border-primary/30 flex items-center justify-center">
                <span className="text-primary text-[11px] font-semibold">U</span>
              </div>
              <div className="text-right">
                <p className="text-[12px] font-medium text-foreground leading-tight">Users</p>
                <p className="text-[10px] text-muted-foreground leading-tight">Online · Read Only</p>
              </div>
            </div>
            {/* Clock */}
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
              </svg>
              <span className="tabular-nums font-mono">14:23:45 EST</span>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  )
}

function PageTitle({ pathname }: { pathname: string }) {
  const map: Record<string, string> = {
    '/': 'System Operations Center',
    '/orders': 'Orders',
    '/reconciliation': 'Reconciliation',
    '/accounts': 'Accounts',
    '/decisions': 'Decisions',
    '/logs': 'Logs',
    '/settings': 'System Settings',
  }
  const title =
    map[pathname] ??
    Object.entries(map).find(([k]) => k !== '/' && pathname.startsWith(k))?.[1] ??
    'Dashboard'
  return <h1 className="text-[15px] font-semibold text-foreground tracking-tight">{title}</h1>
}
