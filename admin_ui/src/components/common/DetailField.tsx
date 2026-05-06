import type { ReactNode } from "react";

interface DetailFieldProps {
  label: string;
  value: ReactNode;
  mono?: boolean;
}

export function DetailField({ label, value, mono = false }: DetailFieldProps) {
  return (
    <div className="flex justify-between items-center py-2">
      <span className="text-sm text-[#64748b]">{label}</span>
      <span className={`text-sm font-medium text-[#0f172a] ${mono ? "font-mono" : ""}`}>
        {value}
      </span>
    </div>
  );
}
