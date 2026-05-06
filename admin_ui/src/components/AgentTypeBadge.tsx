import { cn } from "@/lib/utils";

interface AgentTypeBadgeProps {
  agentType: string;
  className?: string;
}

const STYLES: Record<string, { bg: string; text: string; label: string }> = {
  event_interpretation: { bg: "bg-[#dbeafe]", text: "text-[#1e40af]", label: "EI" },
  ai_risk: { bg: "bg-[#fef3c7]", text: "text-[#92400e]", label: "AR" },
  final_decision_composer: { bg: "bg-[#dcfce7]", text: "text-[#166534]", label: "FDC" },
};

function resolveStyle(agentType: string) {
  if (agentType.includes("event_interpretation")) return STYLES.event_interpretation;
  if (agentType.includes("ai_risk")) return STYLES.ai_risk;
  if (agentType.includes("final_decision_composer")) return STYLES.final_decision_composer;
  return { bg: "bg-[#f1f5f9]", text: "text-[#475569]", label: agentType };
}

export function AgentTypeBadge({ agentType, className }: AgentTypeBadgeProps) {
  const style = resolveStyle(agentType);
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium",
        style.bg,
        style.text,
        className,
      )}
    >
      {style.label}
    </span>
  );
}
