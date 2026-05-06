interface SectionDividerProps {
  label: string;
}

export function SectionDivider({ label }: SectionDividerProps) {
  return (
    <div className="flex items-center gap-3 my-4">
      <span className="text-xs font-medium text-[#64748b] uppercase tracking-wider">{label}</span>
      <div className="flex-1 h-px bg-[#e2e8f0]" />
    </div>
  );
}
