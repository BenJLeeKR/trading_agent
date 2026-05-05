interface SectionDividerProps {
  label: string;
}

export function SectionDivider({ label }: SectionDividerProps) {
  return (
    <div className="section-divider">
      <span className="section-divider-label">{label}</span>
      <div className="section-divider-line" />
    </div>
  );
}
