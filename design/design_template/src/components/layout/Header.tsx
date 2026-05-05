import { Bell, Calendar, ChevronDown } from 'lucide-react'

export default function Header() {
  const today = new Date()
  const formatted = today.toLocaleDateString('en-US', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })

  return (
    <header className="flex items-center justify-between px-6 py-3 bg-white border-b border-gray-100 shrink-0">
      <div>
        <h1 className="text-lg font-semibold text-gray-900">
          Good Morning, Jonathan!
        </h1>
        <p className="text-xs text-gray-400 mt-0.5">
          {"Here's what's happening with your store today"}
        </p>
      </div>

      <div className="flex items-center gap-3">
        {/* Date */}
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-50 border border-gray-100 text-xs text-gray-600">
          <Calendar size={13} className="text-gray-400" />
          <span>{formatted}</span>
        </div>

        {/* Notifications */}
        <button className="relative flex items-center justify-center w-8 h-8 rounded-lg bg-gray-50 border border-gray-100 text-gray-500 hover:bg-gray-100 transition-colors">
          <Bell size={15} />
          <span className="absolute -top-0.5 -right-0.5 flex items-center justify-center w-4 h-4 rounded-full bg-red-500 text-white text-[9px] font-bold">
            7
          </span>
        </button>

        {/* Avatar */}
        <button className="flex items-center gap-1.5 group">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-indigo-600 flex items-center justify-center text-white text-xs font-semibold">
            J
          </div>
          <ChevronDown size={13} className="text-gray-400 group-hover:text-gray-600 transition-colors" />
        </button>
      </div>
    </header>
  )
}
