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
  ListOrdered,
  LineChart,
  Menu,
  X,
  Bot,
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
      { icon: RefreshCcw, label: "정합성 점검", to: "/reconciliation" },
    ],
  },
  {
    title: "기본 운영",
    items: [
      { icon: LineChart, label: "현재가", to: "/operations/realtime-quotes" },
      { icon: FileText, label: "주문내역", to: "/orders" },
      { icon: ListOrdered, label: "체결내역", to: "/fills" },
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
 * Nav sections list — shared by the desktop sidebar and the mobile dropdown
 * ─────────────────────────────────────────── */
function NavSectionsList({
  currentPath,
  onNavigate,
}: {
  currentPath: string;
  onNavigate?: () => void;
}) {
  return (
    <>
      {navSections.map((section) => (
        <div key={section.title} className="mb-4">
          <p className="px-3 py-2 text-xs font-medium text-[#94a3b8] tracking-wider">
            {section.title}
          </p>
          <ul className="space-y-1">
            {section.items.map((item) => {
              const isActive = !item.disabled && (
                item.to === "/"
                  ? currentPath === "/"
                  : currentPath === item.to || currentPath.startsWith(item.to + "/")
              );
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
                      onClick={onNavigate}
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
    </>
  );
}

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
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Close the mobile dropdown whenever the route changes (deep link, back
  // button, or a nav click that didn't go through onNavigate).
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  // Close on Escape while the mobile dropdown is open.
  useEffect(() => {
    if (!mobileMenuOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileMenuOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileMenuOpen]);

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

  const currentPath = location.pathname;

  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth() + 1;
  const d = now.getDate();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const dateStr = `${y}. ${m}. ${d}. ${hh}:${mm}`;

  return (
    <div className="flex h-screen bg-[#f8fafc]">
      {/* ── Sidebar (desktop only, md 이상) ── */}
      <aside className="hidden md:flex h-screen w-[220px] flex-col bg-white border-r border-[#e2e8f0] flex-shrink-0">
        {/* Logo */}
        <div className="flex items-center gap-2 px-5 py-6">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#1e293b]">
            <span className="text-white font-bold text-sm">A</span>
          </div>
          <span className="text-lg font-semibold text-[#0f172a]">운영 콘솔</span>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto px-3">
          <NavSectionsList currentPath={currentPath} />
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
      <div className="relative flex flex-1 flex-col overflow-hidden">
        {/* Header */}
        <header className="flex items-center justify-between bg-white px-4 md:px-6 py-3 border-b border-[#e2e8f0]">
          {/* Left: mobile hamburger + 시스템 타이틀 */}
          <div className="flex items-center gap-4">
            <button
              type="button"
              aria-label={mobileMenuOpen ? "메뉴 닫기" : "메뉴 열기"}
              aria-expanded={mobileMenuOpen}
              onClick={() => setMobileMenuOpen((open) => !open)}
              className="md:hidden flex items-center justify-center h-8 w-8 rounded-lg text-[#64748b] hover:bg-[#f1f5f9] hover:text-[#0f172a]"
            >
              {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#1e293b]">
                <Bot className="h-5 w-5 text-white" />
              </div>
              <span className="text-sm sm:text-base font-semibold text-[#0f172a]">
                Multi Agent Trading System
              </span>
            </div>
          </div>

          {/* Right side: 상태 정보 — 40px 간격 — 날짜 — 읽기 전용 배지 */}
          <div className="flex items-center gap-4">
            <div className="hidden sm:flex items-center gap-6 mr-[40px]">
              <StatusDot label="API: 정상" healthy={apiHealthy} />
              <StatusDot label="DB: 연결됨" healthy={dbHealthy} />
              <div className="flex items-center gap-2">
                <Activity className="h-3.5 w-3.5 text-[#64748b]" />
                <span className="text-xs font-medium text-[#64748b]">
                  {apiHealthy ? "모든 시스템 정상" : "이상 감지"}
                </span>
              </div>
            </div>
            <span className="text-xs text-[#94a3b8]">{dateStr}</span>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#f1f5f9]">
              <span className="flex h-2 w-2 rounded-full bg-[#22c55e]" />
              <span className="text-xs font-medium text-[#0f172a]">읽기 전용</span>
            </div>
          </div>
        </header>

        {/* ── Mobile menu dropdown (md 미만에서만) ──
            헤더 높이는 h-8(32px) 버튼 + py-3(24px) 패딩으로 고정 56px(top-14)이다.
            `fixed`로 뷰포트 기준 배치해 부모의 relative 컨테이닝 블록 크기와
            무관하게 항상 헤더 바로 아래 · 화면 하단까지 정확히 덮도록 한다. */}
        {mobileMenuOpen && (
          <>
            <div
              className="md:hidden fixed inset-x-0 top-14 bottom-0 z-40 bg-black/30"
              onClick={() => setMobileMenuOpen(false)}
              aria-hidden="true"
            />
            <div className="md:hidden fixed inset-x-0 top-14 z-50 max-h-[calc(100vh-3.5rem)] overflow-y-auto bg-white border-b border-[#e2e8f0] shadow-lg px-3 py-3">
              <NavSectionsList currentPath={currentPath} onNavigate={() => setMobileMenuOpen(false)} />
              <div className="border-t border-[#e2e8f0] pt-3 mt-1">
                <button
                  onClick={() => {
                    setMobileMenuOpen(false);
                    logout();
                  }}
                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold text-[#64748b] hover:bg-[#f8fafc] hover:text-[#0f172a] transition-colors text-left"
                >
                  <LogOut className="h-5 w-5" />
                  로그아웃
                </button>
              </div>
            </div>
          </>
        )}

        {/* Page content */}
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
