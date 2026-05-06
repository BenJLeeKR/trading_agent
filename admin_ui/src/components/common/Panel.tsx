import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface PanelProps {
  title?: string;
  subtitle?: string;
  headerRight?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  noPadding?: boolean;
}

export function Panel({
  title,
  subtitle,
  headerRight,
  children,
  className = "",
  bodyClassName = "",
  noPadding = false,
}: PanelProps) {
  return (
    <div className={cn("bg-white rounded-xl border border-[#e2e8f0]", className)}>
      {(title || headerRight) && (
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#e2e8f0]">
          <div>
            {title && <h3 className="text-base font-semibold text-[#0f172a]">{title}</h3>}
            {subtitle && <p className="text-xs text-[#64748b] mt-0.5">{subtitle}</p>}
          </div>
          {headerRight && <div>{headerRight}</div>}
        </div>
      )}
      <div className={cn(noPadding ? "" : "p-5", bodyClassName)}>
        {children}
      </div>
    </div>
  );
}
