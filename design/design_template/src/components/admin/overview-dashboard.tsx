'use client'

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { SummaryCard, MetricRow } from './summary-card'
import { DataTable } from './data-table'
import { Panel } from './panel'
import { WarningBanner } from './warning-banner'
import { OrderStatusBadge, SeverityBadge } from './status-badge'
import { systemHealth, mockOrders, mockLocks, mockReconRuns, degradedAgents } from '@/lib/mock-data'
import type { Order } from '@/lib/mock-data'

const symbolIcon: Record<string, string> = {
  NVDA: '🟢',
  AAPL: '🍎',
  AMZN: '📦',
  TSLA: '⚡',
  MSFT: '🪟',
  GOOGL: '🔍',
}

function SymbolCell({ symbol }: { symbol: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="text-[10px]">{symbolIcon[symbol] ?? '·'}</span>
      <span className="font-medium text-foreground tabular-nums">{symbol}</span>
    </span>
  )
}

function SideCell({ side }: { side: 'Buy' | 'Sell' }) {
  return (
    <span
      className={
        side === 'Buy'
          ? 'text-status-success-fg font-semibold text-[11px]'
          : 'text-status-error-fg font-semibold text-[11px]'
      }
    >
      {side}
    </span>
  )
}

export function OverviewDashboard() {
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null)
  const activeLocks = mockLocks.filter((l) => l.is_active)
  const overdueRuns = mockReconRuns.filter((r) => r.overdue_since)

  return (
    <div className="flex flex-col gap-4 p-5 h-full">
      {/* Summary Cards Row */}
      <div className="grid grid-cols-4 gap-3 shrink-0">
        <SummaryCard
          index={1}
          title="API Health"
          status={systemHealth.api.status}
          statusLabel={systemHealth.api.label}
        >
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <MetricRow label="Latency" value={systemHealth.api.latency} />
            <MetricRow label="Uptime" value={systemHealth.api.uptime} separator />
          </div>
        </SummaryCard>

        <SummaryCard
          index={2}
          title="Database Status"
          status={systemHealth.database.status}
          statusLabel={systemHealth.database.label}
        >
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <MetricRow label="Replicas" value={systemHealth.database.replicas} />
            <MetricRow label="Storage" value={systemHealth.database.storage} separator />
          </div>
        </SummaryCard>

        <SummaryCard
          index={3}
          title="Active Locks Count"
          status={systemHealth.activeLocks.status}
          statusLabel={systemHealth.activeLocks.label}
          to="/reconciliation"
        >
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <MetricRow label="Count" value={`${systemHealth.activeLocks.count} Active`} />
            <MetricRow label="Max" value={systemHealth.activeLocks.max} separator />
          </div>
        </SummaryCard>

        <SummaryCard
          index={4}
          title="Incomplete Recon Runs Count"
          status={systemHealth.incompleteRecon.status}
          statusLabel={systemHealth.incompleteRecon.label}
          to="/reconciliation"
        >
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <MetricRow
              label="Count"
              value={
                <span>
                  {systemHealth.incompleteRecon.pending} Pending,{' '}
                  <span className="text-status-error-fg">{systemHealth.incompleteRecon.overdue} Overdue</span>
                </span>
              }
            />
          </div>
        </SummaryCard>
      </div>

      {/* Critical Banner */}
      <WarningBanner
        level="warning"
        message={`CRITICAL: ${systemHealth.incompleteRecon.overdue} Overdue Reconciliation Runs — Action Required`}
        className="shrink-0"
      />

      {/* Main Body */}
      <div className="flex gap-3 flex-1 min-h-0">
        {/* Recent Orders Table */}
        <Panel
          title="Recent Orders"
          className="flex-1 min-w-0 overflow-hidden"
          bodyClassName="overflow-auto p-0"
          noPadding
          headerRight={
            <Link
              to="/orders"
              className="flex items-center gap-1 text-[11px] text-primary hover:text-primary/80 transition-colors"
            >
              View all <ChevronRight size={12} />
            </Link>
          }
        >
          <DataTable
            data={mockOrders}
            getRowKey={(o) => o.order_request_id}
            selectedKey={selectedOrder?.order_request_id}
            onRowClick={(o) =>
              setSelectedOrder(o.order_request_id === selectedOrder?.order_request_id ? null : o)
            }
            compact
            columns={[
              {
                key: 'symbol',
                header: 'Symbol',
                render: (o) => <SymbolCell symbol={o.symbol} />,
              },
              {
                key: 'side',
                header: 'Side',
                render: (o) => <SideCell side={o.side} />,
              },
              {
                key: 'qty',
                header: 'Quantity',
                className: 'text-right',
                render: (o) => (
                  <span className="tabular-nums text-foreground/80">{o.quantity.toLocaleString()}</span>
                ),
              },
              {
                key: 'status',
                header: 'Status',
                render: (o) => <OrderStatusBadge status={o.status} />,
              },
              {
                key: 'time',
                header: 'Created Time',
                render: (o) => (
                  <span className="text-muted-foreground tabular-nums font-mono text-[11px]">
                    {o.created_at}
                  </span>
                ),
              },
            ]}
          />
        </Panel>

        {/* Operational Signals */}
        <div className="w-72 shrink-0 flex flex-col gap-3 overflow-y-auto">
          {/* Active Lock Warnings */}
          <Panel title="Active Locks Warnings" noPadding>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left text-[10px] font-medium text-muted-foreground/70 uppercase tracking-wide px-4 py-2">Agent ID</th>
                  <th className="text-left text-[10px] font-medium text-muted-foreground/70 uppercase tracking-wide px-4 py-2">Resource</th>
                  <th className="text-left text-[10px] font-medium text-muted-foreground/70 uppercase tracking-wide px-4 py-2">Severity</th>
                </tr>
              </thead>
              <tbody>
                {activeLocks.slice(0, 5).map((lock) => (
                  <tr key={lock.lock_id} className="border-b border-border/40 hover:bg-surface-2/40 transition-colors">
                    <td className="px-4 py-2 text-foreground/85 font-medium">{lock.agent_id}</td>
                    <td className="px-4 py-2 text-muted-foreground truncate max-w-[90px]">{lock.resource}</td>
                    <td className="px-4 py-2"><SeverityBadge severity={lock.severity} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          {/* Incomplete Reconciliation Signals */}
          <Panel title="Incomplete Reconciliation Signals" noPadding>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left text-[10px] font-medium text-muted-foreground/70 uppercase tracking-wide px-4 py-2">Run ID</th>
                  <th className="text-left text-[10px] font-medium text-muted-foreground/70 uppercase tracking-wide px-4 py-2">Status</th>
                  <th className="text-left text-[10px] font-medium text-muted-foreground/70 uppercase tracking-wide px-4 py-2">Overdue</th>
                </tr>
              </thead>
              <tbody>
                {overdueRuns.map((run) => (
                  <tr key={run.reconciliation_run_id} className="border-b border-border/40 hover:bg-surface-2/40 transition-colors">
                    <td className="px-4 py-2 font-mono text-foreground/75 tabular-nums text-[10px]">
                      {run.reconciliation_run_id}
                    </td>
                    <td className="px-4 py-2">
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-surface-3/60 text-foreground/70 border border-border uppercase tracking-wide">
                        Pending
                      </span>
                    </td>
                    <td className="px-4 py-2 text-status-error-fg font-medium text-[10px] tabular-nums">
                      {run.overdue_since}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          {/* Degraded / Reflection Failure Indicators */}
          <Panel title="Reflection Failure / Degraded Status Indicators" noPadding>
            <ul className="divide-y divide-border/40">
              {degradedAgents.map((a, i) => (
                <li key={i} className="flex items-center gap-2.5 px-4 py-2.5 hover:bg-surface-2/40 transition-colors">
                  <span
                    className={
                      a.severity === 'RED'
                        ? 'w-1.5 h-1.5 rounded-full bg-status-error shrink-0 shadow-[0_0_5px_var(--color-status-error)]'
                        : 'w-1.5 h-1.5 rounded-full bg-status-amber shrink-0'
                    }
                  />
                  <span className="text-[11px] font-medium text-foreground/85">{a.agent_id}</span>
                  <span className="text-[11px] text-muted-foreground truncate">{a.issue}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  )
}
