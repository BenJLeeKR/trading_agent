import { MoreHorizontal, MapPin, MessageCircle, Phone } from "lucide-react"

export function TrackingDelivery() {
  return (
    <div className="rounded-xl bg-white p-5 shadow-sm border border-[#e2e8f0] h-full">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-semibold text-[#0f172a]">Tracking Delivery</h3>
        <button className="text-[#94a3b8] hover:text-[#64748b] transition-colors">
          <MoreHorizontal className="h-5 w-5" />
        </button>
      </div>
      
      <p className="text-xs text-[#94a3b8] mb-3">Las Viewed delivery history</p>
      
      {/* Map placeholder */}
      <div className="relative h-32 rounded-lg overflow-hidden bg-[#e2e8f0] mb-4">
        <div className="absolute inset-0 bg-gradient-to-br from-[#dbeafe] to-[#e0f2fe]">
          <svg className="w-full h-full" viewBox="0 0 200 100">
            <path
              d="M10 70 Q50 50, 80 60 T150 40 T190 50"
              stroke="#94a3b8"
              strokeWidth="1"
              fill="none"
              strokeDasharray="4 2"
            />
            <circle cx="80" cy="58" r="4" fill="#2563eb" />
            <circle cx="150" cy="42" r="4" fill="#ef4444" />
            <path d="M78 52 L80 58 L82 52 L80 48 Z" fill="#2563eb" />
          </svg>
        </div>
        <div className="absolute top-2 right-2 flex flex-col gap-1">
          <button className="w-6 h-6 bg-white rounded shadow text-[#64748b] text-sm font-medium hover:bg-[#f8fafc]">+</button>
          <button className="w-6 h-6 bg-white rounded shadow text-[#64748b] text-sm font-medium hover:bg-[#f8fafc]">−</button>
        </div>
      </div>

      {/* Order Info */}
      <div className="mb-4">
        <p className="text-xs text-[#94a3b8]">Order ID:</p>
        <div className="flex items-center justify-between mt-1">
          <p className="text-sm font-semibold text-[#0f172a]">#FR156KL89K</p>
          <button className="rounded-full border border-[#2563eb] px-3 py-1 text-xs font-medium text-[#2563eb] hover:bg-[#eff6ff] transition-colors">
            Checking
          </button>
        </div>
      </div>

      {/* Timeline */}
      <div className="space-y-3">
        <TimelineItem
          icon={<MapPin className="h-3.5 w-3.5 text-[#2563eb]" />}
          title="Total Distance"
          value="868 km"
          time="11:23 AM"
        />
        <TimelineItem
          icon={<div className="h-2 w-2 rounded-full bg-[#94a3b8]" />}
          title="Return"
          value="8 Trips"
          time="10:23AM"
        />
        <TimelineItem
          icon={<div className="h-2 w-2 rounded-full bg-[#64748b]" />}
          title="One-way"
          value="16 Trips"
          time="9:28 AM"
        />
      </div>

      {/* Driver Info */}
      <div className="mt-4 pt-4 border-t border-[#e2e8f0]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img
              src="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=40&h=40&fit=crop&crop=face"
              alt="Driver"
              className="h-10 w-10 rounded-full object-cover"
            />
            <div>
              <p className="text-xs text-[#94a3b8]">Driver</p>
              <p className="text-sm font-semibold text-[#0f172a]">Antoni Jaison</p>
            </div>
          </div>
          <div className="flex gap-2">
            <button className="flex h-9 w-9 items-center justify-center rounded-full bg-[#f8fafc] text-[#64748b] hover:bg-[#e2e8f0] transition-colors">
              <MessageCircle className="h-4 w-4" />
            </button>
            <button className="flex h-9 w-9 items-center justify-center rounded-full bg-[#f8fafc] text-[#64748b] hover:bg-[#e2e8f0] transition-colors">
              <Phone className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function TimelineItem({
  icon,
  title,
  value,
  time,
}: {
  icon: React.ReactNode
  title: string
  value: string
  time: string
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-6 w-6 items-center justify-center">{icon}</div>
      <div className="flex-1">
        <p className="text-xs text-[#94a3b8]">{title}</p>
        <p className="text-sm font-semibold text-[#0f172a]">{value}</p>
      </div>
      <p className="text-xs text-[#94a3b8]">{time}</p>
    </div>
  )
}
