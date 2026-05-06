import { cn } from "@/lib/utils"

type AgentTypeBadgeVariant = "ei" | "ar" | "fdc"

interface AgentTypeBadgeProps {
  agentType: string
  className?: string
}

export function AgentTypeBadge({ agentType, className }: AgentTypeBadgeProps) {
  const getVariant = (type: string): AgentTypeBadgeVariant => {
    if (type.includes("event_interpretation")) return "ei"
    if (type.includes("ai_risk")) return "ar"
    if (type.includes("final_decision_composer")) return "fdc"
    return "ei"
  }

  const variant = getVariant(agentType)
  const variants: Record<AgentTypeBadgeVariant, string> = {
    ei: "bg-[#dbeafe] text-[#1e40af]",
    ar: "bg-[#fef3c7] text-[#92400e]",
    fdc: "bg-[#dcfce7] text-[#166534]",
  }

  const labelMap: Record<AgentTypeBadgeVariant, string> = {
    ei: "EI",
    ar: "AR",
    fdc: "FDC",
  }

  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium",
        variants[variant],
        className
      )}
    >
      {labelMap[variant]}
    </span>
  )
}
