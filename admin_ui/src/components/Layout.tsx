import { useState, useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { getHealth } from "../api/client";
import {
  LayoutDashboard,
  FileText,
  RefreshCcw,
  Wallet,
  Brain,
  Building2,
  Server,
  ShieldCheck,
  LogOut,
  Activity,
  Zap,
  AlertCircle,
  Search,
} from "lucide-react";
import { cn } from "@/lib/utils";

/* ───────────────────────────────────────────
 * Navigation sections (template pattern)
 * ─────────────────────────────────────────── */
interface NavItem {
  icon: React.ElementType;
  label: string;
  to: string;
  disabled?: boolean;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const navSections: NavSection[] = [
  {
    title: "운영 모니터링",
    items: [
      { icon: Activity, label: "운영 대시보드", to: "/" },
      { icon: AlertCircle, label: "운영 경고", to: "/operations/alerts" },
      { icon: Search, label: "주문 추적", to: "/operations/orders" },
    ],
  },
  {
    title: "기본 운영",
    items: [
      { icon: FileText, label: "주문", to: "/orders" },
      { icon: RefreshCcw, label: "정합성 점검", to: "/reconciliation" },
      { icon: Wallet, label: "계좌", to: "/accounts" },
      { icon: Brain, label: "의사결정", to: "/decisions" },
      { icon: Zap, label: "에이전트 실행", to: "/agent-runs" },
    ],
  },
  {
    title: "예약됨",
    items: [
      { icon: Building2, label: "브로커", to: "#", disabled: true },
      { icon: Server, label: "시스템", to: "#", disabled: true },
      { icon: ShieldCheck, label: "관리", to: "#", disabled: true },
    ],
  },
];

/* ───────────────────────────────────────────
 * Status indicator
 * ─────────────────────────────────────────── */
function StatusDot({ label, healthy }: { label: string; healthy: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span className={cn("flex h-2 w-2 rounded-full", healthy ? "bg-[#22c55e]" : "bg-[#ef4444]")} />
      <span className="text-xs font-medium text-[#64748b]">{label}</span>
    </div>
  );
}

/* ───────────────────────────────────────────
 * Layout
 * ─────────────────────────────────────────── */
export function Layout() {
  const { token, logout } = useAuth();
  const location = useLocation();
  const [apiHealthy, setApiHealthy] = useState(true);
  const [dbHealthy, setDbHealthy] = useState(true);

  // Health check
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const h = await getHealth();
        if (!cancelled) {
          setApiHealthy(h.status === "ok");
          setDbHealthy(h.database === "connected" || h.database === "ok" || h.database === "in_memory");
        }
      } catch {
        if (!cancelled) {
          setApiHealthy(false);
          setDbHealthy(false);
        }
      }
    };
    check();
    const interval = setInterval(check, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const currentPath = location.pathname === "/" ? "/" : `/${location.pathname.split("/")[1]}`;

  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth() + 1;
  const d = now.getDate();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const dateStr = `${y}. ${m}. ${d}. ${hh}:${mm}`;

  return (
    <div className="flex h-screen bg-[#f8fafc]">
      {/* ── Sidebar ── */}
      <aside className="flex h-screen w-[220px] flex-col bg-white border-r border-[#e2e8f0] flex-shrink-0">
        {/* Logo */}
        <div className="flex items-center gap-2 px-5 py-6">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#1e293b]">
            <span className="text-white font-bold text-sm">A</span>
          </div>
          <span className="text-lg font-semibold text-[#0f172a]">운영 콘솔</span>
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
                  const isActive = !item.disabled && currentPath === item.to;
                  return (
                    <li key={item.label}>
                      {item.disabled ? (
                        <button
                          disabled
                          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold text-[#cbd5e1] cursor-not-allowed text-left"
                        >
                          <item.icon className="h-5 w-5" />
                          {item.label}
                          <span className="ml-auto text-[10px] text-[#94a3b8] bg-[#f1f5f9] px-1.5 py-0.5 rounded">
                            Soon
                          </span>
                        </button>
                      ) : (
                        <NavLink
                          to={item.to}
                          end={item.to === "/"}
                          className={cn(
                            "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold transition-colors",
                            isActive
                              ? "bg-[#f1f5f9] text-[#0f172a]"
                              : "text-[#64748b] hover:bg-[#f8fafc] hover:text-[#0f172a]"
                          )}
                        >
                          <item.icon className="h-5 w-5" />
                          {item.label}
                        </NavLink>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        {/* Bottom: Logout */}
        <div className="border-t border-[#e2e8f0] px-3 py-4">
          <ul className="space-y-1">
            <li>
              <button
                onClick={logout}
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold text-[#64748b] hover:bg-[#f8fafc] hover:text-[#0f172a] transition-colors text-left"
              >
                <LogOut className="h-5 w-5" />
                로그아웃
              </button>
            </li>
          </ul>
        </div>
      </aside>

      {/* ── Main area ── */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header */}
        <header className="flex items-center justify-between bg-white px-6 py-3 border-b border-[#e2e8f0]">
          {/* Status Strip */}
          <div className="flex items-center gap-6">
            <StatusDot label="API: 정상" healthy={apiHealthy} />
            <StatusDot label="DB: 연결됨" healthy={dbHealthy} />
            <div className="flex items-center gap-2">
              <Activity className="h-3.5 w-3.5 text-[#64748b]" />
              <span className="text-xs font-medium text-[#64748b]">
                {apiHealthy ? "모든 시스템 정상" : "이상 감지"}
              </span>
            </div>
          </div>

          {/* Right side */}
          <div className="flex items-center gap-4">
            <span className="text-xs text-[#94a3b8]">{dateStr}</span>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#f1f5f9]">
              <span className="flex h-2 w-2 rounded-full bg-[#22c55e]" />
              <span className="text-xs font-medium text-[#0f172a]">읽기 전용</span>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
