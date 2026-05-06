import { cn } from "@/lib/utils"

interface SummaryCardProps {
  title: string
  subtitle: string
  value: string
  change: string
  changeType: "positive" | "negative"
  icon: React.ReactNode
}

export function SummaryCard({
  title,
  subtitle,
  value,
  change,
  changeType,
  icon,
}: SummaryCardProps) {
  return (
    <div className="rounded-xl bg-white p-5 shadow-sm border border-[#e2e8f0]">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-medium text-[#64748b]">{title}</h3>
          <p className="mt-1 text-xs text-[#94a3b8]">{subtitle}</p>
          <p className="mt-3 text-2xl font-semibold text-[#0f172a]">{value}</p>
          <p
            className={cn(
              "mt-1 text-xs font-medium",
              changeType === "positive" ? "text-[#10b981]" : "text-[#ef4444]"
            )}
          >
            {change}
          </p>
        </div>
        <div className="flex-shrink-0">{icon}</div>
      </div>
    </div>
  )
}
