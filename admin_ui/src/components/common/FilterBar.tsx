import { Search, Filter, X } from "lucide-react";

interface FilterOption {
  label: string;
  value: string;
}

interface FilterBarProps {
  searchPlaceholder?: string;
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  filters?: {
    key: string;
    label: string;
    options: FilterOption[];
    value?: string;
    onChange?: (value: string) => void;
  }[];
  onClearAll?: () => void;
}

export function FilterBar({
  searchPlaceholder = "검색...",
  searchValue = "",
  onSearchChange,
  filters = [],
  onClearAll,
}: FilterBarProps) {
  const hasActiveFilters = searchValue || filters.some((f) => f.value);

  return (
    <div className="flex items-center gap-3 mb-4 flex-wrap">
      {/* Search */}
      <div className="relative flex-1 max-w-xs min-w-[180px]">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#94a3b8]" />
        <input
          type="text"
          placeholder={searchPlaceholder}
          value={searchValue}
          onChange={(e) => onSearchChange?.(e.target.value)}
          className="w-full pl-9 pr-3 py-2 text-sm border border-[#e2e8f0] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#3b82f6] focus:border-transparent"
        />
      </div>

      {/* Filters */}
      {filters.map((filter) => (
        <div key={filter.key} className="relative">
          <select
            aria-label={filter.label}
            value={filter.value || ""}
            onChange={(e) => filter.onChange?.(e.target.value)}
            className="appearance-none pl-3 pr-8 py-2 text-sm border border-[#e2e8f0] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#3b82f6] focus:border-transparent text-[#0f172a]"
          >
            <option value="">{filter.label}</option>
            {filter.options.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <Filter className="absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[#94a3b8] pointer-events-none" />
        </div>
      ))}

      {/* Clear All */}
      {hasActiveFilters && (
        <button
          onClick={onClearAll}
          className="flex items-center gap-1.5 px-3 py-2 text-sm text-[#64748b] hover:text-[#0f172a] transition-colors"
        >
          <X className="h-4 w-4" />
          초기화
        </button>
      )}
    </div>
  );
}
