interface StatusBadgeProps {
  status: string;
}

const STATUS_COLORS: Record<string, string> = {
  // Order statuses
  pending: "var(--pico-primary)",
  submitted: "var(--pico-primary)",
  partially_filled: "var(--pico-warning)",
  filled: "var(--pico-ins-color)",
  cancelled: "var(--pico-muted-color)",
  rejected: "var(--pico-del-color)",
  reconcile_required: "var(--pico-warning)",
  reflection_failed: "var(--pico-del-color)",
  // Health
  ok: "var(--pico-ins-color)",
  healthy: "var(--pico-ins-color)",
  degraded: "var(--pico-warning)",
  error: "var(--pico-del-color)",
  // Lock
  active: "var(--pico-warning)",
  expired: "var(--pico-muted-color)",
  // Reconciliation
  running: "var(--pico-primary)",
  completed: "var(--pico-ins-color)",
  resolved: "var(--pico-ins-color)",
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const color = STATUS_COLORS[status.toLowerCase()] ?? "var(--pico-primary)";
  return (
    <span
      style={{
        display: "inline-block",
        padding: "0.15rem 0.5rem",
        fontSize: "0.8rem",
        fontWeight: 600,
        borderRadius: "4px",
        color: "#fff",
        backgroundColor: color,
      }}
    >
      {status}
    </span>
  );
}
