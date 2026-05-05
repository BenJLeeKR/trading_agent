'use client'

import { useState, useMemo } from 'react'
import { cn } from '@/lib/utils'
import { Panel, DetailField, SectionDivider } from './panel'
import { DataTable } from './data-table'
import { ReconStatusBadge, SeverityBadge } from './status-badge'
import { WarningBanner } from './warning-banner'
import { mockReconRuns, mockLocks } from '@/lib/mock-data'
import type { ReconciliationRun, Lock, ReconciliationStatus } from '@/lib/mock-data'

const STATUS_FILTERS: { label: string; value: ReconciliationStatus | 'all' }[] = [
  { label: 'All', value: 'all' },
  { label: 'Pending', value: 'pending' },
  { label: 'Running', value: 'running' },
  { label: 'Resolved', value: 'resolved' },
  { label: 'Reflection Failed', value: 'reflection_failed' },
]

export function ReconciliationView() {
  const [statusFilter, setStatusFilter] = useState<ReconciliationStatus | 'all'>('all')
  const [selectedRun, setSelectedRun] = useState<ReconciliationRun | null>(null)
  const [selectedLock, setSelectedLock] = useState<Lock | null>(null)

  const activeLocks = mockLocks.filter((l) => l.is_active)
  const overdueCount = mockReconRuns.filter((r) => r.overdue_since).length

  const filteredRuns = useMemo(() => {
    if (statusFilter === 'all') return mockReconRuns
    return mockReconRuns.filter((r) => r.status === statusFilter)
  }, [statusFilter])

  return (
    <div className="flex flex-col gap-4 p-5 h-full overflow-y-auto">
      {overdueCount > 0 && (
        <WarningBanner
          level="warning"
          message={`${activeLocks.length} Active Locks detected — ${overdueCount} Reconciliation Runs are overdue. Immediate review required.`}
        />
      )}

      <div className="flex items-center gap-2 shrink-0">
        <span className="text-[11px] font-medium text-muted-foreground/60 uppercase tracking-wide">Filter:</span>
        {STATUS_FILTERS.map(({ label, value }) => (
          <button
            key={value}
            onClick={() => setStatusFilter(value)}
            className={cn(
              'px-3 py-1 rounded-md text-[11px] font-medium border transition-colors',
              statusFilter === value
                ? 'bg-primary/15 border-primary/40 text-primary'
                : 'bg-surface-2/50 border-border text-muted-foreground hover:text-foreground'
            )}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
          {filteredRuns.length} runs
        </span>
      </div>

      <div className="flex gap-3 flex-1 min-h-0">
        <div className="flex-1 flex flex-col gap-3 min-w-0 overflow-hidden">
          <Panel
            title="Reconciliation Runs"
            className="flex-1 overflow-hidden"
            bodyClassName="p-0 overflow-auto"
            noPadding
          >
            <DataTable
              data={filteredRuns}
              getRowKey={(r) => r.reconciliation_run_id}
              selectedKey={selectedRun?.reconciliation_run_id}
              onRowClick={(r) =>
                setSelectedRun(
                  r.reconciliation_run_id === selectedRun?.reconciliation_run_id ? null : r
                )
              }
              columns={[
                {
                  key: 'id',
                  header: 'Run ID',
                  render: (r) => (
                    <span className="font-mono text-[11px] text-foreground/80 tabular-nums">
                      {r.reconciliation_run_id}
                    </span>
                  ),
                },
                {
                  key: 'account',
                  header: 'Account',
                  render: (r) => (
                    <span className="text-foreground/85 font-medium">{r.account_id}</span>
                  ),
                },
                {
                  key: 'trigger',
                  header: 'Trigger',
                  render: (r) => (
                    <span className="text-muted-foreground capitalize text-[11px]">
                      {r.trigger_type}
                    </span>
                  ),
                },
                {
                  key: 'status',
                  header: 'Status',
                  render: (r) => <ReconStatusBadge status={r.status} />,
                },
                {
                  key: 'started',
                  header: 'Started At',
                  render: (r) => (
                    <span className="text-muted-foreground tabular-nums font-mono text-[10px]">
                      {r.started_at}
                    </span>
                  ),
                },
                {
                  key: 'overdue',
                  header: 'Overdue',
                  render: (r) =>
                    r.overdue_since ? (
                      <span className="text-status-error-fg font-semibold text-[11px] tabular-nums">
                        {r.overdue_since}
                      </span>
                    ) : (
                      <span className="text-muted-foreground/40 text-[11px]">—</span>
                    ),
                },
              ]}
            />
          </Panel>

          <Panel
            title="Active Locks"
            subtitle={`${activeLocks.length} active`}
            className="overflow-hidden"
            bodyClassName="p-0 overflow-auto"
            noPadding
          >
            <DataTable
              data={mockLocks}
              getRowKey={(l) => l.lock_id}
              selectedKey={selectedLock?.lock_id}
              onRowClick={(l) =>
                setSelectedLock(l.lock_id === selectedLock?.lock_id ? null : l)
              }
              columns={[
                {
                  key: 'id',
                  header: 'Lock ID',
                  render: (l) => (
                    <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                      {l.lock_id}
                    </span>
                  ),
                },
                {
                  key: 'agent',
                  header: 'Agent',
                  render: (l) => (
                    <span className="text-foreground/85 font-medium">{l.agent_id}</span>
                  ),
                },
                {
                  key: 'resource',
                  header: 'Resource',
                  render: (l) => (
                    <span className="text-muted-foreground text-[11px]">{l.resource}</span>
                  ),
                },
                {
                  key: 'severity',
                  header: 'Severity',
                  render: (l) => <SeverityBadge severity={l.severity} />,
                },
                {
                  key: 'state',
                  header: 'State',
                  render: (l) => (
                    <span
                      className={cn(
                        'text-[11px] font-semibold',
                        l.is_active ? 'text-status-amber-fg' : 'text-muted-foreground/50'
                      )}
                    >
                      {l.is_active ? 'Active' : 'Expired'}
                    </span>
                  ),
                },
                {
                  key: 'locked',
                  header: 'Locked At',
                  render: (l) => (
                    <span className="text-muted-foreground tabular-nums font-mono text-[10px]">
                      {l.locked_at}
                    </span>
                  ),
                },
                {
                  key: 'expires',
                  header: 'Expires',
                  render: (l) => (
                    <span className="text-muted-foreground tabular-nums font-mono text-[10px]">
                      {l.expires_at}
                    </span>
                  ),
                },
              ]}
            />
          </Panel>
        </div>

        {(selectedRun || selectedLock) && (
          <div className="w-72 shrink-0 overflow-y-auto flex flex-col gap-3">
            {selectedRun && <ReconRunDetail run={selectedRun} />}
            {selectedLock && <LockDetail lock={selectedLock} />}
          </div>
        )}
      </div>
    </div>
  )
}

function ReconRunDetail({ run }: { run: ReconciliationRun }) {
  return (
    <Panel title="Run Detail">
      <div className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-2">
          <span className="font-mono text-[12px] text-foreground/80 tabular-nums">
            {run.reconciliation_run_id}
          </span>
          <ReconStatusBadge status={run.status} />
        </div>
        <SectionDivider label="Fields" />
        <div className="grid grid-cols-1 gap-2.5">
          <DetailField label="Account ID" value={run.account_id} mono />
          <DetailField
            label="Trigger Type"
            value={<span className="capitalize">{run.trigger_type}</span>}
          />
          <DetailField label="Started At" value={run.started_at} mono />
          {run.overdue_since && (
            <DetailField
              label="Overdue Since"
              value={
                <span className="text-status-error-fg font-semibold">{run.overdue_since}</span>
              }
            />
          )}
        </div>
      </div>
    </Panel>
  )
}

function LockDetail({ lock }: { lock: Lock }) {
  return (
    <Panel title="Lock Detail">
      <div className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-2">
          <span className="font-mono text-[12px] text-foreground/80 tabular-nums">
            {lock.lock_id}
          </span>
          <SeverityBadge severity={lock.severity} />
        </div>
        <SectionDivider label="Fields" />
        <div className="grid grid-cols-1 gap-2.5">
          <DetailField label="Agent ID" value={lock.agent_id} />
          <DetailField label="Resource" value={lock.resource} />
          <DetailField
            label="State"
            value={
              <span
                className={
                  lock.is_active ? 'text-status-amber-fg font-semibold' : 'text-muted-foreground'
                }
              >
                {lock.is_active ? 'Active' : 'Expired'}
              </span>
            }
          />
          <DetailField label="Locked At" value={lock.locked_at} mono />
          <DetailField label="Expires At" value={lock.expires_at} mono />
          {lock.reason && <DetailField label="Reason" value={lock.reason} />}
        </div>
      </div>
    </Panel>
  )
}
