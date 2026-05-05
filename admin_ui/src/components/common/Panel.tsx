import type { ReactNode } from "react";

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
    <div className={`panel ${className}`}>
      {(title || headerRight) && (
        <div className="panel-header">
          <div>
            {title && <h3 className="panel-title">{title}</h3>}
            {subtitle && <p className="panel-subtitle">{subtitle}</p>}
          </div>
          {headerRight && <div className="panel-header-right">{headerRight}</div>}
        </div>
      )}
      <div className={`panel-body${noPadding ? " panel-body--no-padding" : ""} ${bodyClassName}`}>
        {children}
      </div>
    </div>
  );
}
