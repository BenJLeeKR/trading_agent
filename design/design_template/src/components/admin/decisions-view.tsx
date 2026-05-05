'use client'

import { useState, useMemo } from 'react'
import { cn } from '@/lib/utils'
import { Panel, DetailField, SectionDivider } from './panel'
import { DataTable } from './data-table'
import { StatusBadge } from './status-badge'
import { mockDecisions } from '@/lib/mock-data'
import type { Decision, Side } from '@/lib/mock-data'

const RISK_LEVELS = ['low', 'medium', 'high']
const ALL_SIDES: Side[] = ['Buy', 'Sell']
const ALL_TYPES = [...new Set(mockDecisions.map((d) => d.decision_type))]

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color =
    pct >= 85
      ? 'bg-status-success'
      : pct >= 70
      ? 'bg-status-info'
      : pct >= 60
      ? 'bg-status-amber'
      : 'bg-status-error'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-surface-3 overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-all', color)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span
        className={cn(
          'tabular-nums text-[11px] font-semibold w-9 text-right',
          pct >= 85
            ? 'text-status-success-fg'
            : pct >= 70
            ? 'text-status-info-fg'
            : pct >= 60
            ? 'text-status-amber-fg'
            : 'text-status-error-fg'
        )}
      >
        {pct}%
      </span>
    </div>
  )
}

function RiskBadge({ level }: { level?: string }) {
  if (!level) return null
  const variant =
    level === 'high' ? 'error' : level === 'medium' ? 'warning' : 'success'
  return <StatusBadge label={level} variant={variant} />
}

export function DecisionsView() {
  const [selected, setSelected] = useState<Decision | null>(mockDecisions[0])
  const [filterSide, setFilterSide] = useState<Side | 'all'>('all')
  const [filterType, setFilterType] = useState('all')
  const [filterRisk, setFilterRisk] = useState('all')

  const filtered = useMemo(() => {
    return mockDecisions.filter((d) => {
      if (filterSide !== 'all' && d.side !== filterSide) return false
      if (filterType !== 'all' && d.decision_type !== filterType) return false
      if (filterRisk !== 'all' && d.risk_level !== filterRisk) return false
      return true
    })
  }, [filterSide, filterType, filterRisk])

  return (
    <div className="flex flex-col gap-0 h-full">
      {/* Filter Bar */}
      <div className="shrink-0 flex flex-wrap items-center gap-3 px-5 py-3 border-b border-border bg-card/20">
        <FilterGroup
          label="Side"
          options={['all', ...ALL_SIDES]}
          value={filterSide}
          onChange={(v) => setFilterSide(v as Side | 'all')}
        />
        <FilterGroup
          label="Type"
          options={['all', ...ALL_TYPES]}
          value={filterType}
          onChange={setFilterType}
          capitalize
        />
        <FilterGroup
          label="Risk"
          options={['all', ...RISK_LEVELS]}
          value={filterRisk}
          onChange={setFilterRisk}
          capitalize
        />
        <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
          {filtered.length} decisions
        </span>
      </div>

      {/* Body */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <div className="flex-1 overflow-hidden">
          <Panel
            className="h-full rounded-none border-0 border-r border-border"
            bodyClassName="p-0 overflow-auto"
            noPadding
          >
            <DataTable
              data={filtered}
              getRowKey={(d) => d.trade_decision_id}
              selectedKey={selected?.trade_decision_id}
              onRowClick={(d) =>
                setSelected(
                  d.trade_decision_id === selected?.trade_decision_id ? null : d
                )
              }
              columns={[
                {
                  key: 'id',
                  header: 'Decision ID',
                  render: (d) => (
                    <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                      {d.trade_decision_id}
                    </span>
                  ),
                },
                {
                  key: 'ticker',
                  header: 'Ticker',
                  render: (d) => (
                    <span className="font-semibold text-foreground">{d.ticker}</span>
                  ),
                },
                {
                  key: 'side',
                  header: 'Side',
                  render: (d) => (
                    <span
                      className={cn(
                        'text-[11px] font-semibold',
                        d.side === 'Buy' ? 'text-status-success-fg' : 'text-status-error-fg'
                      )}
                    >
                      {d.side}
                    </span>
                  ),
                },
                {
                  key: 'type',
                  header: 'Type',
                  render: (d) => (
                    <span className="text-muted-foreground text-[11px] capitalize">
                      {d.decision_type.replace(/_/g, ' ')}
                    </span>
                  ),
                },
                {
                  key: 'confidence',
                  header: 'Confidence',
                  className: 'min-w-[140px]',
                  render: (d) => <ConfidenceBar value={d.confidence} />,
                },
                {
                  key: 'risk',
                  header: 'Risk',
                  render: (d) => <RiskBadge level={d.risk_level} />,
                },
                {
                  key: 'agent',
                  header: 'Agent',
                  render: (d) => (
                    <span className="text-muted-foreground text-[11px]">{d.agent_label}</span>
                  ),
                },
                {
                  key: 'created',
                  header: 'Created',
                  render: (d) => (
                    <span className="text-muted-foreground tabular-nums font-mono text-[10px]">
                      {d.created_at}
                    </span>
                  ),
                },
              ]}
            />
          </Panel>
        </div>

        {selected && (
          <div className="w-80 shrink-0 overflow-y-auto border-l border-border bg-surface-1/50">
            <DecisionDetailPanel decision={selected} />
          </div>
        )}
      </div>
    </div>
  )
}

function DecisionDetailPanel({ decision }: { decision: Decision }) {
  const pct = Math.round(decision.confidence * 100)
  return (
    <div className="p-4 flex flex-col gap-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[15px] font-semibold text-foreground">{decision.ticker}</p>
          <p className="text-[11px] text-muted-foreground mt-0.5 font-mono">
            {decision.trade_decision_id}
          </p>
        </div>
        <RiskBadge level={decision.risk_level} />
      </div>

      <div className="p-3 rounded-lg bg-surface-2 border border-border">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] text-muted-foreground font-medium">Confidence Score</span>
          <span
            className={cn(
              'text-[18px] font-bold tabular-nums',
              pct >= 85
                ? 'text-status-success-fg'
                : pct >= 70
                ? 'text-status-info-fg'
                : pct >= 60
                ? 'text-status-amber-fg'
                : 'text-status-error-fg'
            )}
          >
            {pct}%
          </span>
        </div>
        <ConfidenceBar value={decision.confidence} />
      </div>

      <SectionDivider label="Decision Details" />
      <div className="grid grid-cols-2 gap-3">
        <DetailField
          label="Side"
          value={
            <span
              className={cn(
                'font-semibold',
                decision.side === 'Buy' ? 'text-status-success-fg' : 'text-status-error-fg'
              )}
            >
              {decision.side}
            </span>
          }
        />
        <DetailField
          label="Type"
          value={
            <span className="capitalize">{decision.decision_type.replace(/_/g, ' ')}</span>
          }
        />
        <DetailField label="Agent" value={decision.agent_label} />
        <DetailField label="Context ID" value={decision.decision_context_id} mono />
      </div>

      <DetailField label="Created At" value={decision.created_at} mono />

      {decision.rationale && (
        <>
          <SectionDivider label="Rationale" />
          <p className="text-[12px] text-foreground/75 leading-relaxed">{decision.rationale}</p>
        </>
      )}

      {decision.context_summary && (
        <>
          <SectionDivider label="Decision Context" />
          <p className="text-[12px] text-foreground/75 leading-relaxed">
            {decision.context_summary}
          </p>
        </>
      )}
    </div>
  )
}

function FilterGroup({
  label,
  options,
  value,
  onChange,
  capitalize = false,
}: {
  label: string
  options: string[]
  value: string
  onChange: (v: string) => void
  capitalize?: boolean
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground/60 font-medium">
        {label}
      </span>
      {options.map((opt) => (
        <button
          key={opt}
          onClick={() => onChange(opt)}
          className={cn(
            'px-2.5 py-1 rounded text-[11px] font-medium border transition-colors',
            capitalize && 'capitalize',
            value === opt
              ? 'bg-primary/15 border-primary/40 text-primary'
              : 'bg-surface-2/50 border-border text-muted-foreground hover:text-foreground'
          )}
        >
          {opt === 'all' ? 'All' : opt.replace(/_/g, ' ')}
        </button>
      ))}
    </div>
  )
}
