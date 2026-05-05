'use client'

import { AlertTriangle, XCircle, Info } from 'lucide-react'
import { cn } from '@/lib/utils'

type BannerLevel = 'warning' | 'critical' | 'info'

interface WarningBannerProps {
  level?: BannerLevel
  message: string
  className?: string
}

const levelConfig: Record<BannerLevel, { icon: React.ElementType; cls: string }> = {
  warning: {
    icon: AlertTriangle,
    cls: 'bg-status-amber/10 border-status-amber/35 text-status-amber-fg',
  },
  critical: {
    icon: XCircle,
    cls: 'bg-status-error/10 border-status-error/35 text-status-error-fg',
  },
  info: {
    icon: Info,
    cls: 'bg-status-info/10 border-status-info/35 text-status-info-fg',
  },
}

export function WarningBanner({ level = 'warning', message, className }: WarningBannerProps) {
  const { icon: Icon, cls } = levelConfig[level]
  return (
    <div
      className={cn(
        'flex items-center gap-2.5 px-4 py-2.5 rounded-lg border text-[12px] font-medium',
        cls,
        className
      )}
    >
      <Icon size={14} className="shrink-0" />
      <span>{message}</span>
    </div>
  )
}
