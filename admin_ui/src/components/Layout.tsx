import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import {
  LayoutDashboard,
  ArrowLeftRight,
  GitCompare,
  Building2,
  ClipboardCheck,
  ChevronLeft,
  Bell,
  Calendar,
  LogOut,
  Bot,
} from "lucide-react";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/orders", label: "Orders", icon: ArrowLeftRight },
  { to: "/reconciliation", label: "Reconciliation", icon: GitCompare },
  { to: "/accounts", label: "Accounts", icon: Building2 },
  { to: "/decisions", label: "Decisions", icon: ClipboardCheck },
] as const;

const PAGE_SUBTITLES: Record<string, string> = {
  "/": "Trading overview & management",
  "/orders": "Monitor trade order activity",
  "/reconciliation": "Reconciliation runs & lock management",
  "/accounts": "Client account details & positions",
  "/decisions": "AI trade decisions & context",
};

export function Layout() {
  const { token, logout } = useAuth();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const truncatedToken = token ? `${token.slice(0, 8)}...` : "—";

  const today = new Date();
  const formatted = today.toLocaleDateString("en-US", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  const currentPath = Object.keys(PAGE_SUBTITLES).find(
    (p) =>
      p === "/"
        ? location.pathname === "/"
        : location.pathname.startsWith(p),
  ) ?? "/";
  const currentLabel =
    NAV_ITEMS.find((n) => n.to === currentPath)?.label ?? "Admin";

  return (
    <div className="app-shell">
      {/* Sidebar */}
      <aside
        className={`sidebar${collapsed ? " sidebar--collapsed" : ""}`}
      >
        {/* Logo */}
        <div className="sidebar-brand">
          <div className="sidebar-brand-icon">
            <Bot size={16} />
          </div>
          {!collapsed && (
            <div className="sidebar-brand-text">
              <div className="sidebar-brand-title">AgentTrade</div>
              <div className="sidebar-brand-status">
                <span className="sidebar-brand-dot" />
                <span className="sidebar-brand-live">Live</span>
              </div>
            </div>
          )}
        </div>

        {/* Toggle button */}
        <button
          onClick={() => setCollapsed((v) => !v)}
          className="sidebar-toggle"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <ChevronLeft
            size={12}
            style={{
              transform: collapsed ? "rotate(180deg)" : "rotate(0deg)",
              transition: "transform 0.2s",
            }}
          />
        </button>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-3">
          {!collapsed && (
            <div className="sidebar-nav-section">NAVIGATION</div>
          )}
          {collapsed && <div className="mt-2" />}
          <ul className="sidebar-nav">
            {NAV_ITEMS.map((item) => (
              <li key={item.to} className="sidebar-nav-item">
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    `sidebar-nav-link${isActive ? " active" : ""}`
                  }
                  title={collapsed ? item.label : undefined}
                >
                  <item.icon size={16} className="sidebar-nav-icon" />
                  {!collapsed && (
                    <span className="sidebar-nav-text">{item.label}</span>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        {/* Token + logout */}
        <div className="sidebar-footer">
          {!collapsed && (
            <div className="sidebar-footer-status">
              <div className="sidebar-footer-status-content">
                <span className="sidebar-footer-status-dot" />
                <div className="sidebar-footer-status-text">
                  <p className="sidebar-footer-status-title">All systems normal</p>
                  <p className="sidebar-footer-status-sub">Token: {truncatedToken}</p>
                </div>
              </div>
            </div>
          )}
          {collapsed && (
            <div className="sidebar-footer-collapsed-dot" />
          )}
          <button
            onClick={logout}
            className="sidebar-logout-btn"
          >
            <LogOut size={13} />
            {!collapsed && <span>Logout</span>}
          </button>
          {!collapsed && (
            <div className="sidebar-footer-version">
              v2.4.1 — build 20260505
            </div>
          )}
        </div>
      </aside>

      {/* Main area */}
      <div className="main-area">
        <header className="top-header">
          <div className="top-header-left">
            <h1 className="top-header-greeting">{currentLabel}</h1>
            <p className="top-header-date">{PAGE_SUBTITLES[currentPath]}</p>
          </div>
          <div className="top-header-right">
            {/* Date badge */}
            <div className="top-header-date-badge">
              <Calendar size={13} />
              <span>{formatted}</span>
            </div>
            {/* Notification bell */}
            <button className="top-header-notif-btn">
              <Bell size={15} />
              <span className="top-header-notif-dot">3</span>
            </button>
            {/* Avatar */}
            <button className="top-header-avatar-btn">
              <div className="top-header-avatar">A</div>
            </button>
          </div>
        </header>
        <main className="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
