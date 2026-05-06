import { cn } from "@/lib/utils"

interface StatusCardProps {
  title: string
  value: string | number
  status: "healthy" | "warning" | "error" | "neutral"
  subtitle?: string
}

export function StatusCard({ title, value, status, subtitle }: StatusCardProps) {
  const statusColors = {
    healthy: "bg-[#dcfce7] text-[#166534]",
    warning: "bg-[#fef3c7] text-[#92400e]",
    error: "bg-[#fee2e2] text-[#991b1b]",
    neutral: "bg-[#f1f5f9] text-[#475569]",
  }

  const dotColors = {
    healthy: "bg-[#22c55e]",
    warning: "bg-[#f59e0b]",
    error: "bg-[#ef4444]",
    neutral: "bg-[#94a3b8]",
  }

  return (
    <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-medium text-[#64748b]">{title}</span>
        <div className={cn("flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium", statusColors[status])}>
          <span className={cn("w-1.5 h-1.5 rounded-full", dotColors[status])} />
          {status === "healthy" ? "Healthy" : status === "warning" ? "Warning" : status === "error" ? "Error" : "Info"}
        </div>
      </div>
      <p className="text-2xl font-semibold text-[#0f172a]">{value}</p>
      {subtitle && (
        <p className="text-xs text-[#94a3b8] mt-1">{subtitle}</p>
      )}
    </div>
  )
}
