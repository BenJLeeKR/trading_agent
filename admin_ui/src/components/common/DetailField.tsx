import type { ReactNode } from "react";

interface DetailFieldProps {
  label: string;
  value: ReactNode;
  mono?: boolean;
}

export function DetailField({ label, value, mono = false }: DetailFieldProps) {
  return (
    <div className="detail-field">
      <span className="detail-field-label">{label}</span>
      <span className={`detail-field-value${mono ? " detail-field-value--mono" : ""}`}>
        {value}
      </span>
    </div>
  );
}
