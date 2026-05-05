'use client'

import { cn } from '@/lib/utils'

interface PanelProps {
  title?: string
  subtitle?: string
  headerRight?: React.ReactNode
  children: React.ReactNode
  className?: string
  bodyClassName?: string
  noPadding?: boolean
}

export function Panel({
  title,
  subtitle,
  headerRight,
  children,
  className,
  bodyClassName,
  noPadding = false,
}: PanelProps) {
  return (
    <div className={cn('rounded-lg border border-border bg-surface-1 flex flex-col', className)}>
      {(title || headerRight) && (
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <div>
            {title && (
              <h2 className="text-[13px] font-semibold text-foreground leading-tight">{title}</h2>
            )}
            {subtitle && (
              <p className="text-[11px] text-muted-foreground mt-0.5">{subtitle}</p>
            )}
          </div>
          {headerRight && <div className="shrink-0">{headerRight}</div>}
        </div>
      )}
      <div className={cn(noPadding ? '' : 'p-4', 'flex-1 min-h-0', bodyClassName)}>
        {children}
      </div>
    </div>
  )
}

interface DetailFieldProps {
  label: string
  value: React.ReactNode
  mono?: boolean
}

export function DetailField({ label, value, mono = false }: DetailFieldProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] font-medium text-muted-foreground/70 uppercase tracking-wider">
        {label}
      </span>
      <span className={cn('text-[12px] text-foreground/90 leading-snug', mono && 'font-mono')}>
        {value}
      </span>
    </div>
  )
}

interface SectionDividerProps {
  label: string
}

export function SectionDivider({ label }: SectionDividerProps) {
  return (
    <div className="flex items-center gap-2 my-3">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground/50 font-medium">
        {label}
      </span>
      <div className="flex-1 h-px bg-border/60" />
    </div>
  )
}
