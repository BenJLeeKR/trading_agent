import { AlertTriangle, AlertCircle, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

type BannerVariant = "warning" | "error" | "info";

interface WarningBannerProps {
  variant: BannerVariant;
  title: string;
  message?: string;
  onDismiss?: () => void;
  className?: string;
}

const variants: Record<BannerVariant, { bg: string; border: string; icon: React.ElementType; iconColor: string }> = {
  warning: {
    bg: "bg-[#fffbeb]",
    border: "border-[#fbbf24]",
    icon: AlertTriangle,
    iconColor: "text-[#f59e0b]",
  },
  error: {
    bg: "bg-[#fef2f2]",
    border: "border-[#f87171]",
    icon: AlertCircle,
    iconColor: "text-[#ef4444]",
  },
  info: {
    bg: "bg-[#eff6ff]",
    border: "border-[#60a5fa]",
    icon: Info,
    iconColor: "text-[#3b82f6]",
  },
};

export function WarningBanner({
  variant,
  title,
  message,
  onDismiss,
  className,
}: WarningBannerProps) {
  const config = variants[variant];
  const Icon = config.icon;

  return (
    <div
      className={cn(
        "flex items-start gap-3 p-4 rounded-lg border",
        config.bg,
        config.border,
        className
      )}
    >
      <Icon className={cn("h-5 w-5 flex-shrink-0 mt-0.5", config.iconColor)} />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-[#0f172a]">{title}</p>
        {message && (
          <p className="text-sm text-[#64748b] mt-0.5">{message}</p>
        )}
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="flex-shrink-0 p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
