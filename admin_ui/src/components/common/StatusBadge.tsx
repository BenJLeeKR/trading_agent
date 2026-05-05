interface StatusBadgeProps {
  status: string;
}

/** Map a status string to a CSS variant class */
function statusToVariant(status: string): string {
  const s = status.toLowerCase();
  // Success group
  if (["filled", "completed", "resolved", "ok", "healthy"].includes(s)) {
    return "badge--success";
  }
  // Warning group
  if (
    [
      "reconcile_required",
      "degraded",
      "active",
      "partial",
      "partially_filled",
    ].includes(s)
  ) {
    return "badge--warning";
  }
  // Error group
  if (
    ["rejected", "reflection_failed", "error", "failed"].includes(s)
  ) {
    return "badge--error";
  }
  // Info / amber group
  if (["pending", "submitted", "running"].includes(s)) {
    return "badge--info";
  }
  // Muted / expired / cancelled
  if (["cancelled", "expired"].includes(s)) {
    return "badge--muted";
  }
  // Default
  return "badge--info";
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const variant = statusToVariant(status);
  return <span className={`badge ${variant}`}>{status}</span>;
}
