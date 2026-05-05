import { Package, CheckSquare, XSquare, Star } from 'lucide-react'

interface StatCardProps {
  icon: React.ElementType
  iconBg: string
  iconColor: string
  label: string
  value: string | number
  change: string
  positive: boolean
}

function StatCard({ icon: Icon, iconBg, iconColor, label, value, change, positive }: StatCardProps) {
  return (
    <div className="flex-1 bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex items-center gap-4">
      <div
        className="flex items-center justify-center w-10 h-10 rounded-lg shrink-0"
        style={{ backgroundColor: iconBg }}
      >
        <Icon size={20} style={{ color: iconColor }} />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-gray-400 mb-0.5 truncate">{label}</p>
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-xl font-bold text-gray-900">{value}</span>
          <span
            className="text-xs font-medium px-1.5 py-0.5 rounded-full"
            style={{
              backgroundColor: positive ? '#ecfdf5' : '#fef2f2',
              color: positive ? '#10b981' : '#ef4444',
            }}
          >
            {change}
          </span>
        </div>
      </div>
    </div>
  )
}

export default function StatCards() {
  const stats: StatCardProps[] = [
    {
      icon: Package,
      iconBg: '#eff6ff',
      iconColor: '#3b82f6',
      label: 'Total products',
      value: 250,
      change: '+2.5%',
      positive: true,
    },
    {
      icon: CheckSquare,
      iconBg: '#ecfdf5',
      iconColor: '#10b981',
      label: 'Completed order',
      value: 124,
      change: '+2.5%',
      positive: true,
    },
    {
      icon: XSquare,
      iconBg: '#fef2f2',
      iconColor: '#ef4444',
      label: 'Canceled order',
      value: 14,
      change: '-1.5%',
      positive: false,
    },
    {
      icon: Star,
      iconBg: '#fffbeb',
      iconColor: '#f59e0b',
      label: 'Top products',
      value: 119,
      change: '+2.5%',
      positive: true,
    },
  ]

  return (
    <div className="flex gap-4">
      {stats.map((s) => (
        <StatCard key={s.label} {...s} />
      ))}
    </div>
  )
}
