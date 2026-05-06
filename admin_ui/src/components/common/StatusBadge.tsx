import { cn } from "@/lib/utils";

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral";

interface StatusBadgeProps {
  /** Explicit variant (template style) */
  variant?: BadgeVariant;
  /** Status string (legacy style — auto-mapped to variant) */
  status?: string;
  children?: React.ReactNode;
  className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  success: "bg-[#dcfce7] text-[#166534]",
  warning: "bg-[#fef3c7] text-[#92400e]",
  error: "bg-[#fee2e2] text-[#991b1b]",
  info: "bg-[#dbeafe] text-[#1e40af]",
  neutral: "bg-[#f1f5f9] text-[#475569]",
};

/** Map a status string to a BadgeVariant */
function statusToVariant(s: string): BadgeVariant {
  const lower = s.toLowerCase();
  if (["filled", "completed", "resolved", "ok", "healthy", "active", "buy", "long"].includes(lower)) {
    return "success";
  }
  if (["reconcile_required", "degraded", "partial", "partially_filled", "pending"].includes(lower)) {
    return "warning";
  }
  if (["rejected", "reflection_failed", "error", "failed", "sell", "short", "restricted"].includes(lower)) {
    return "error";
  }
  if (["submitted", "running", "margin", "info"].includes(lower)) {
    return "info";
  }
  if (["cancelled", "expired"].includes(lower)) {
    return "neutral";
  }
  return "info";
}

export function StatusBadge({ variant, status, children, className }: StatusBadgeProps) {
  // Determine variant: explicit > auto-mapped from status > default "info"
  const resolvedVariant: BadgeVariant = variant ?? (status ? statusToVariant(status) : "info");
  const displayText = children ?? status ?? "";

  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium",
        variantStyles[resolvedVariant],
        className
      )}
    >
      {displayText}
    </span>
  );
}
