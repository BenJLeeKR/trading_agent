import { MoreHorizontal } from "lucide-react"

export function TotalTrips() {
  return (
    <div className="rounded-xl bg-white p-5 shadow-sm border border-[#e2e8f0]">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-base font-semibold text-[#0f172a]">Total Trips</h3>
          <p className="text-xs text-[#94a3b8]">Vehicles Operating on The Road</p>
        </div>
        <button className="text-[#94a3b8] hover:text-[#64748b] transition-colors">
          <MoreHorizontal className="h-5 w-5" />
        </button>
      </div>
      
      <div className="flex items-end justify-between">
        <div>
          <p className="text-4xl font-bold text-[#0f172a]">24</p>
          <p className="mt-2 text-sm text-[#64748b]">
            Hired Transportation <span className="text-[#f97316] font-medium">5 Trips</span>
          </p>
        </div>
        <div className="w-28 h-20">
          <svg viewBox="0 0 120 60" className="w-full h-full">
            <rect x="5" y="25" width="110" height="30" rx="2" fill="#e2e8f0" />
            <rect x="10" y="15" width="15" height="35" rx="2" fill="#94a3b8" />
            <circle cx="25" cy="52" r="6" fill="#475569" />
            <circle cx="100" cy="52" r="6" fill="#475569" />
            <rect x="30" y="20" width="60" height="25" rx="2" fill="#64748b" />
            <rect x="35" y="23" width="20" height="12" rx="1" fill="#cbd5e1" />
            <rect x="60" y="23" width="25" height="12" rx="1" fill="#cbd5e1" />
          </svg>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-2">
        <span className="flex h-2.5 w-2.5 rounded-full bg-[#2563eb]"></span>
        <span className="text-sm font-medium text-[#2563eb]">On-Route</span>
      </div>
    </div>
  )
}
