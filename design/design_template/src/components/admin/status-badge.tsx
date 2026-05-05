'use client'

import { cn } from '@/lib/utils'
import type { OrderStatus, ReconciliationStatus, Severity } from '@/lib/mock-data'

type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral' | 'amber'

function getOrderStatusVariant(status: OrderStatus): BadgeVariant {
  switch (status) {
    case 'filled': return 'success'
    case 'partially_filled': return 'info'
    case 'pending_submit':
    case 'submitted':
    case 'acknowledged':
    case 'validated':
    case 'draft': return 'neutral'
    case 'rejected':
    case 'error': return 'error'
    case 'cancelled':
    case 'expired': return 'neutral'
    case 'reconcile_required': return 'amber'
    default: return 'neutral'
  }
}

function getReconStatusVariant(status: ReconciliationStatus): BadgeVariant {
  switch (status) {
    case 'resolved': return 'success'
    case 'running': return 'info'
    case 'reflection_failed': return 'error'
    case 'pending': return 'amber'
    default: return 'neutral'
  }
}

function getSeverityVariant(sev: Severity): BadgeVariant {
  switch (sev) {
    case 'GREEN': return 'success'
    case 'AMBER': return 'amber'
    case 'RED': return 'error'
  }
}

const variantClasses: Record<BadgeVariant, string> = {
  success: 'bg-status-success/15 text-status-success-fg border-status-success/30',
  warning: 'bg-status-warning/15 text-status-warning-fg border-status-warning/30',
  error: 'bg-status-error/15 text-status-error-fg border-status-error/30',
  info: 'bg-status-info/15 text-status-info-fg border-status-info/30',
  neutral: 'bg-surface-3/60 text-foreground/70 border-border',
  amber: 'bg-status-amber/15 text-status-amber-fg border-status-amber/30',
}

function StatusDot({ variant }: { variant: BadgeVariant }) {
  const dotClass: Record<BadgeVariant, string> = {
    success: 'bg-status-success',
    warning: 'bg-status-warning',
    error: 'bg-status-error',
    info: 'bg-status-info',
    neutral: 'bg-foreground/40',
    amber: 'bg-status-amber',
  }
  return <span className={cn('inline-block w-1.5 h-1.5 rounded-full shrink-0', dotClass[variant])} />
}

interface StatusBadgeProps {
  label: string
  variant: BadgeVariant
  dot?: boolean
  className?: string
}

export function StatusBadge({ label, variant, dot = false, className }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium border tracking-wide uppercase',
        variantClasses[variant],
        className
      )}
    >
      {dot && <StatusDot variant={variant} />}
      {label}
    </span>
  )
}

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  const label = status.replace(/_/g, ' ')
  return <StatusBadge label={label} variant={getOrderStatusVariant(status)} />
}

export function ReconStatusBadge({ status }: { status: ReconciliationStatus }) {
  const label = status.replace(/_/g, ' ')
  return <StatusBadge label={label} variant={getReconStatusVariant(status)} />
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <StatusBadge label={severity} variant={getSeverityVariant(severity)} dot />
}

export function HealthDot({ status }: { status: Severity }) {
  const cls: Record<Severity, string> = {
    GREEN: 'bg-status-success shadow-[0_0_6px_var(--color-status-success)]',
    AMBER: 'bg-status-amber shadow-[0_0_6px_var(--color-status-amber)]',
    RED: 'bg-status-error shadow-[0_0_6px_var(--color-status-error)]',
  }
  return (
    <span className={cn('inline-block w-2 h-2 rounded-full shrink-0', cls[status])} />
  )
}

export function HealthLabel({ status, label }: { status: Severity; label: string }) {
  const textCls: Record<Severity, string> = {
    GREEN: 'text-status-success-fg',
    AMBER: 'text-status-amber-fg',
    RED: 'text-status-error-fg',
  }
  const bgCls: Record<Severity, string> = {
    GREEN: 'bg-status-success/15 border-status-success/25',
    AMBER: 'bg-status-amber/15 border-status-amber/25',
    RED: 'bg-status-error/15 border-status-error/25',
  }
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[11px] font-semibold tracking-wide uppercase',
      bgCls[status], textCls[status]
    )}>
      <HealthDot status={status} />
      {label}
    </span>
  )
}
