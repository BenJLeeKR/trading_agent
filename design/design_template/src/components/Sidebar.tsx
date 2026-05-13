import { cn } from "@/lib/utils"
import {
  LayoutDashboard,
  FileText,
  RefreshCcw,
  Wallet,
  Brain,
  Zap,
  Building2,
  Server,
  ShieldCheck,
  LogOut,
  Activity,
  AlertCircle,
} from "lucide-react"

interface NavItem {
  icon: React.ElementType
  label: string
  active?: boolean
  disabled?: boolean
}

interface NavSection {
  title: string
  items: NavItem[]
}

const navSections: NavSection[] = [
  {
    title: "운영 모니터링",
    items: [
      { icon: LayoutDashboard, label: "운영 대시보드", active: true },
      { icon: AlertCircle, label: "운영 경고" },
      { icon: Activity, label: "주문 추적" },
    ],
  },
  {
    title: "기본 운영",
    items: [
      { icon: FileText, label: "주문" },
      { icon: RefreshCcw, label: "정합성 점검" },
      { icon: Wallet, label: "계좌" },
      { icon: Brain, label: "판단" },
      { icon: Zap, label: "에이전트 실행" },
    ],
  },
  {
    title: "예약됨",
    items: [
      { icon: Building2, label: "브로커", disabled: true },
      { icon: Server, label: "시스템", disabled: true },
      { icon: ShieldCheck, label: "관리", disabled: true },
    ],
  },
]

const bottomItems: NavItem[] = [
  { icon: LogOut, label: "로그아웃" },
]

interface SidebarProps {
  activeItem?: string
  onNavigate?: (item: string) => void
}

export function Sidebar({ activeItem = "Overview", onNavigate }: SidebarProps) {
  return (
    <aside className="flex h-screen w-[220px] flex-col bg-white border-r border-[#e2e8f0]">
      {/* Logo */}
      <div className="flex items-center gap-2 px-5 py-6">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#1e293b]">
          <span className="text-white font-bold text-sm">A</span>
        </div>
        <span className="text-lg font-semibold text-[#0f172a]">Admin Console</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3">
        {navSections.map((section) => (
          <div key={section.title} className="mb-4">
            <p className="px-3 py-2 text-xs font-medium text-[#94a3b8] tracking-wider">
              {section.title}
            </p>
            <ul className="space-y-1">
              {section.items.map((item) => {
                const isActive = item.label === activeItem
                return (
                  <li key={item.label}>
                    <button
                      onClick={() => !item.disabled && onNavigate?.(item.label)}
                      disabled={item.disabled}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors text-left",
                        isActive
                          ? "bg-[#f1f5f9] text-[#0f172a]"
                          : item.disabled
                          ? "text-[#cbd5e1] cursor-not-allowed"
                          : "text-[#64748b] hover:bg-[#f8fafc] hover:text-[#0f172a]"
                      )}
                    >
                      <item.icon className="h-5 w-5" />
                      {item.label}
                      {item.disabled && (
                        <span className="ml-auto text-[10px] text-[#94a3b8] bg-[#f1f5f9] px-1.5 py-0.5 rounded">
                          Soon
                        </span>
                      )}
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Bottom items */}
      <div className="border-t border-[#e2e8f0] px-3 py-4">
        <ul className="space-y-1">
          {bottomItems.map((item) => (
            <li key={item.label}>
              <button
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-[#64748b] hover:bg-[#f8fafc] hover:text-[#0f172a] transition-colors text-left"
              >
                <item.icon className="h-5 w-5" />
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  )
}
