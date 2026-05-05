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
              <div className="sidebar-brand-subtitle">
                Operator Console{" "}
                <span className="sidebar-brand-badge">· READ ONLY</span>
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
          <div className="sidebar-nav-section">Main Menu</div>
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

        {/* User area */}
        <div className="sidebar-user">
          <div className="sidebar-user-avatar">A</div>
          {!collapsed && (
            <div className="sidebar-user-info">
              <div className="sidebar-user-name">Admin</div>
              <div className="sidebar-user-role">Read Only</div>
            </div>
          )}
        </div>

        {/* Token + logout */}
        <div className="sidebar-footer">
          <div
            style={{
              marginBottom: "0.35rem",
              fontSize: "0.75rem",
              lineHeight: 1.3,
            }}
          >
            <div>Token: {truncatedToken}</div>
          </div>
          <button
            onClick={logout}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
              width: "100%",
              padding: "0.35rem 0.6rem",
              fontSize: "0.8rem",
              borderRadius: "6px",
              border: "1px solid var(--border-color)",
              background: "transparent",
              color: "var(--text-muted)",
              cursor: "pointer",
              transition: "color 0.12s ease",
            }}
          >
            <LogOut size={13} />
            <span>Logout</span>
          </button>
          <div className="sidebar-footer-version">
            v2.4.1 — build 20260505
          </div>
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
