'use client'

import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { HealthLabel } from './status-badge'
import type { Severity } from '@/lib/mock-data'

interface SummaryCardProps {
  index: number
  title: string
  status: Severity
  statusLabel: string
  to?: string
  children: React.ReactNode
  className?: string
}

const borderAccent: Record<Severity, string> = {
  GREEN: 'border-t-status-success/50',
  AMBER: 'border-t-status-amber/60',
  RED: 'border-t-status-error/60',
}

export function SummaryCard({
  index,
  title,
  status,
  statusLabel,
  to,
  children,
  className,
}: SummaryCardProps) {
  const inner = (
    <div
      className={cn(
        'relative flex flex-col gap-2 p-3.5 rounded-lg bg-surface-1 border border-border border-t-2 transition-colors group',
        borderAccent[status],
        to ? 'hover:bg-surface-2 cursor-pointer' : '',
        className
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[10px] font-medium text-muted-foreground/60 tabular-nums shrink-0">
            {index}.
          </span>
          <span className="text-[12px] font-medium text-foreground/80 truncate">{title}</span>
        </div>
        {to && (
          <ChevronRight
            size={13}
            className="text-muted-foreground/40 group-hover:text-muted-foreground shrink-0 mt-0.5 transition-colors"
          />
        )}
      </div>

      {/* Status */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-muted-foreground/60 font-medium">Status:</span>
        <HealthLabel status={status} label={statusLabel} />
      </div>

      {/* Metrics */}
      <div className="text-[11px] text-muted-foreground leading-relaxed">
        {children}
      </div>
    </div>
  )

  if (to) {
    return <Link to={to} className="block">{inner}</Link>
  }
  return inner
}

interface MetricRowProps {
  label: string
  value: React.ReactNode
  separator?: boolean
}

export function MetricRow({ label, value, separator = false }: MetricRowProps) {
  return (
    <>
      {separator && <span className="text-border mx-1">|</span>}
      <span>
        <span className="text-muted-foreground/70">{label}: </span>
        <span className="font-semibold text-foreground/90 tabular-nums">{value}</span>
      </span>
    </>
  )
}
