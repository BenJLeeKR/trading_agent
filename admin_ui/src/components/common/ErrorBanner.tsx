import { AlertCircle, X } from "lucide-react";

interface ErrorBannerProps {
  message: string;
  onDismiss?: () => void;
}

export function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  return (
    <div className="flex items-start gap-3 p-4 rounded-lg border bg-[#fef2f2] border-[#f87171]">
      <AlertCircle className="h-5 w-5 flex-shrink-0 mt-0.5 text-[#ef4444]" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-[#0f172a]">{message}</p>
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          aria-label="Dismiss"
          className="flex-shrink-0 p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
