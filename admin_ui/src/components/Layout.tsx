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
    title: "ACTIVE",
    items: [
      { icon: LayoutDashboard, label: "Overview", to: "/" },
      { icon: FileText, label: "Orders", to: "/orders" },
      { icon: RefreshCcw, label: "Reconciliation", to: "/reconciliation" },
      { icon: Wallet, label: "Accounts", to: "/accounts" },
      { icon: Brain, label: "Decisions", to: "/decisions" },
      { icon: Zap, label: "Agent Runs", to: "/agent-runs" },
    ],
  },
  {
    title: "RESERVED",
    items: [
      { icon: Building2, label: "Broker", to: "#", disabled: true },
      { icon: Server, label: "System", to: "#", disabled: true },
      { icon: ShieldCheck, label: "Admin", to: "#", disabled: true },
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
  const dateStr = now.toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="flex h-screen bg-[#f8fafc]">
      {/* ── Sidebar ── */}
      <aside className="flex h-screen w-[220px] flex-col bg-white border-r border-[#e2e8f0] flex-shrink-0">
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
                  const isActive = !item.disabled && currentPath === item.to;
                  return (
                    <li key={item.label}>
                      {item.disabled ? (
                        <button
                          disabled
                          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-[#cbd5e1] cursor-not-allowed text-left"
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
                            "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
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
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-[#64748b] hover:bg-[#f8fafc] hover:text-[#0f172a] transition-colors text-left"
              >
                <LogOut className="h-5 w-5" />
                Log Out
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
            <StatusDot label="API: Operational" healthy={apiHealthy} />
            <StatusDot label="DB: Connected" healthy={dbHealthy} />
            <div className="flex items-center gap-2">
              <Activity className="h-3.5 w-3.5 text-[#64748b]" />
              <span className="text-xs font-medium text-[#64748b]">
                {apiHealthy ? "All systems normal" : "Issues detected"}
              </span>
            </div>
          </div>

          {/* Right side */}
          <div className="flex items-center gap-4">
            <span className="text-xs text-[#94a3b8]">{dateStr}</span>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#f1f5f9]">
              <span className="flex h-2 w-2 rounded-full bg-[#22c55e]" />
              <span className="text-xs font-medium text-[#0f172a]">
                {token ? `${token.slice(0, 8)}...` : "Read-only"}
              </span>
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
