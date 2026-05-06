import { Activity } from "lucide-react"

interface HeaderProps {
  title?: string
}

export function Header({ title }: HeaderProps) {
  return (
    <header className="flex items-center justify-between bg-white px-6 py-3 border-b border-[#e2e8f0]">
      {/* Status Strip */}
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2">
          <span className="flex h-2 w-2 rounded-full bg-[#22c55e]" />
          <span className="text-xs font-medium text-[#64748b]">API: Operational</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex h-2 w-2 rounded-full bg-[#22c55e]" />
          <span className="text-xs font-medium text-[#64748b]">DB: Connected</span>
        </div>
        <div className="flex items-center gap-2">
          <Activity className="h-3.5 w-3.5 text-[#64748b]" />
          <span className="text-xs font-medium text-[#64748b]">Last sync: 30s ago</span>
        </div>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-4">
        <span className="text-xs text-[#94a3b8]">
          {new Date().toLocaleString("en-US", {
            weekday: "short",
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#f1f5f9]">
          <span className="flex h-2 w-2 rounded-full bg-[#22c55e]" />
          <span className="text-xs font-medium text-[#0f172a]">Read-only</span>
        </div>
      </div>
    </header>
  )
}
