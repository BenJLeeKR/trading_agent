import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  ShoppingCart,
  Package,
  Users,
  BarChart2,
  Megaphone,
  Tag,
  Store,
  ShoppingBag,
  Plus,
  ChevronLeft,
  Bot,
} from 'lucide-react'

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

const mainNavItems = [
  { to: '/overview', icon: LayoutDashboard, label: 'Overview' },
  { to: '/orders', icon: ShoppingCart, label: 'Orders', badge: 10 },
  { to: '/products', icon: Package, label: 'Products' },
  { to: '/analytics', icon: BarChart2, label: 'Analytics' },
]

const customerNavItems = [
  { to: '/customers', icon: Users, label: 'Customer' },
  { to: '/marketing', icon: Megaphone, label: 'Marketing' },
  { to: '/discount', icon: Tag, label: 'Discount' },
]

const salesChannelItems = [
  { to: '/online-store', icon: Store, label: 'Online store' },
  { to: '/point-of-sale', icon: ShoppingBag, label: 'Point of sale' },
]

const appItems = [
  { icon: '🛍️', label: 'Shopee', color: '#ee4d2d' },
  { icon: '🎵', label: 'Tiktok', color: '#000000' },
  { icon: '🟢', label: 'Tokopedia', color: '#42b549' },
]

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  return (
    <aside
      className="relative flex flex-col h-full bg-white border-r border-gray-100 transition-all duration-200"
      style={{ width: collapsed ? 64 : 220 }}
    >
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-4 py-4 border-b border-gray-100">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-blue-600 text-white shrink-0">
          <Bot size={16} />
        </div>
        {!collapsed && (
          <span className="font-semibold text-gray-900 text-sm tracking-tight">AgentTrade</span>
        )}
      </div>

      {/* Toggle button */}
      <button
        onClick={onToggle}
        className="absolute -right-3 top-[52px] z-10 flex items-center justify-center w-6 h-6 rounded-full bg-white border border-gray-200 shadow-sm text-gray-500 hover:text-gray-700 transition-colors"
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        <ChevronLeft
          size={12}
          style={{ transform: collapsed ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}
        />
      </button>

      <nav className="flex-1 overflow-y-auto py-3">
        {/* Main Menu */}
        <NavSection label="Main Menu" collapsed={collapsed} />
        {mainNavItems.map((item) => (
          <SidebarItem key={item.to} {...item} collapsed={collapsed} />
        ))}

        <div className="my-2" />

        {/* Customers etc */}
        {customerNavItems.map((item) => (
          <SidebarItem key={item.to} {...item} collapsed={collapsed} />
        ))}

        {/* Sales Channel */}
        <NavSection label="Sales Channel" collapsed={collapsed} />
        {salesChannelItems.map((item) => (
          <SidebarItem key={item.to} {...item} collapsed={collapsed} />
        ))}

        {/* Apps */}
        <NavSection label="Apps" collapsed={collapsed} />
        {appItems.map((item) => (
          <AppItem key={item.label} {...item} collapsed={collapsed} />
        ))}

        {/* Add apps */}
        <button
          className="flex items-center gap-2 w-full px-3 py-2 text-blue-500 hover:bg-blue-50 transition-colors rounded-lg mx-1 text-xs font-medium"
          style={{ width: 'calc(100% - 8px)' }}
        >
          <Plus size={14} className="shrink-0" />
          {!collapsed && <span>Add apps</span>}
        </button>
      </nav>

      {/* Bottom user */}
      <div className="px-3 py-3 border-t border-gray-100">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-400 to-indigo-600 shrink-0 flex items-center justify-center text-white text-xs font-semibold">
            J
          </div>
          {!collapsed && (
            <div className="overflow-hidden">
              <p className="text-xs font-medium text-gray-800 truncate">Jonathan</p>
              <p className="text-xs text-gray-400 truncate">Admin</p>
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}

function NavSection({ label, collapsed }: { label: string; collapsed: boolean }) {
  if (collapsed) return <div className="my-2 border-t border-gray-100 mx-2" />
  return (
    <p className="px-4 pt-3 pb-1 text-xs font-semibold text-gray-400 uppercase tracking-wider">
      {label}
    </p>
  )
}

interface SidebarItemProps {
  to: string
  icon: React.ElementType
  label: string
  badge?: number
  collapsed: boolean
}

function SidebarItem({ to, icon: Icon, label, badge, collapsed }: SidebarItemProps) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center gap-2.5 mx-1 px-3 py-2 rounded-lg text-sm transition-colors ${
          isActive
            ? 'bg-blue-50 text-blue-600 font-medium'
            : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
        }`
      }
      style={{ width: 'calc(100% - 8px)' }}
      title={collapsed ? label : undefined}
    >
      <Icon size={16} className="shrink-0" />
      {!collapsed && (
        <>
          <span className="flex-1">{label}</span>
          {badge != null && (
            <span className="flex items-center justify-center w-5 h-5 rounded-full bg-red-500 text-white text-xs font-semibold">
              {badge}
            </span>
          )}
        </>
      )}
    </NavLink>
  )
}

function AppItem({
  icon,
  label,
  collapsed,
}: {
  icon: string
  label: string
  collapsed: boolean
}) {
  return (
    <div
      className="flex items-center gap-2.5 mx-1 px-3 py-2 rounded-lg text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900 cursor-pointer transition-colors"
      style={{ width: 'calc(100% - 8px)' }}
      title={collapsed ? label : undefined}
    >
      <span className="shrink-0 text-base leading-none">{icon}</span>
      {!collapsed && <span>{label}</span>}
    </div>
  )
}
