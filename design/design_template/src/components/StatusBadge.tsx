import { cn } from "@/lib/utils"

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral"

interface StatusBadgeProps {
  variant: BadgeVariant
  children: React.ReactNode
  className?: string
}

export function StatusBadge({ variant, children, className }: StatusBadgeProps) {
  const variants: Record<BadgeVariant, string> = {
    success: "bg-[#dcfce7] text-[#166534]",
    warning: "bg-[#fef3c7] text-[#92400e]",
    error: "bg-[#fee2e2] text-[#991b1b]",
    info: "bg-[#dbeafe] text-[#1e40af]",
    neutral: "bg-[#f1f5f9] text-[#475569]",
  }

  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium",
        variants[variant],
        className
      )}
    >
      {children}
    </span>
  )
}
