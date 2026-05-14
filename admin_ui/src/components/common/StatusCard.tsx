import { cn } from "@/lib/utils";

type StatusVariant = "healthy" | "warning" | "error" | "neutral";

interface StatusCardProps {
  title: string;
  value: string | number;
  status: StatusVariant;
  subtitle?: string;
}

const statusColors: Record<StatusVariant, string> = {
  healthy: "bg-[#dcfce7] text-[#166534]",
  warning: "bg-[#fef3c7] text-[#92400e]",
  error: "bg-[#fee2e2] text-[#991b1b]",
  neutral: "bg-[#f1f5f9] text-[#475569]",
};

const dotColors: Record<StatusVariant, string> = {
  healthy: "bg-[#22c55e]",
  warning: "bg-[#f59e0b]",
  error: "bg-[#ef4444]",
  neutral: "bg-[#94a3b8]",
};

const statusLabels: Record<StatusVariant, string> = {
  healthy: "정상",
  warning: "주의",
  error: "오류",
  neutral: "정보",
};

export function StatusCard({ title, value, status, subtitle }: StatusCardProps) {
  return (
    <div className="bg-white rounded-lg border border-[#e2e8f0] p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-[#64748b]">{title}</span>
        <div
          className={cn(
            "flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium",
            statusColors[status],
          )}
        >
          <span className={cn("w-1 h-1 rounded-full", dotColors[status])} />
          {statusLabels[status]}
        </div>
      </div>
      <p className="text-lg font-semibold text-[#0f172a]">{value}</p>
      {subtitle && <p className="text-[10px] text-[#94a3b8] mt-0.5">{subtitle}</p>}
    </div>
  );
}
