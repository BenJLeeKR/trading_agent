import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

/* Simple inline SVG icon paths */
function DashboardIcon() {
  return (
    <svg className="sidebar-nav-icon" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="3" />
      <path d="M3 12h3m12 0h3M12 3v3m0 12v3" />
    </svg>
  );
}
function OrdersIcon() {
  return (
    <svg className="sidebar-nav-icon" viewBox="0 0 24 24">
      <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
      <line x1="3" y1="6" x2="21" y2="6" />
      <path d="M16 10a4 4 0 0 1-8 0" />
    </svg>
  );
}
function ReconIcon() {
  return (
    <svg className="sidebar-nav-icon" viewBox="0 0 24 24">
      <path d="M21 2v6h-6" />
      <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
      <path d="M3 12a9 9 0 0 0 15 6.7L21 16" />
    </svg>
  );
}
function AccountsIcon() {
  return (
    <svg className="sidebar-nav-icon" viewBox="0 0 24 24">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}
function DecisionsIcon() {
  return (
    <svg className="sidebar-nav-icon" viewBox="0 0 24 24">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="12" y1="18" x2="12" y2="12" />
      <line x1="9" y1="15" x2="15" y2="15" />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg className="sidebar-nav-chevron" viewBox="0 0 24 24">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  );
}

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: DashboardIcon },
  { to: "/orders", label: "Orders", icon: OrdersIcon },
  { to: "/reconciliation", label: "Reconciliation", icon: ReconIcon },
  { to: "/accounts", label: "Accounts", icon: AccountsIcon },
  { to: "/decisions", label: "Decisions", icon: DecisionsIcon },
] as const;

function PageTitle({ pathname }: { pathname: string }) {
  const item = NAV_ITEMS.find(
    (n) => n.to === "/" ? pathname === "/" : pathname.startsWith(n.to)
  );
  return <>{item?.label ?? "Admin"}</>;
}

export function Layout() {
  const { token, logout } = useAuth();
  const location = useLocation();
  const truncatedToken = token ? `${token.slice(0, 8)}...` : "—";

  return (
    <div className="app-shell">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-brand-icon">
            <span>A</span>
          </div>
          <div className="sidebar-brand-text">
            <div className="sidebar-brand-title">AITrading Co.</div>
            <div className="sidebar-brand-subtitle">
              Operator Console <span className="sidebar-brand-badge">· READ ONLY</span>
            </div>
          </div>
        </div>

        <ul className="sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <li key={item.to} className="sidebar-nav-item">
              <NavLink
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `sidebar-nav-link${isActive ? " active" : ""}`
                }
              >
                <item.icon />
                <span className="sidebar-nav-text">{item.label}</span>
                {location.pathname === item.to ||
                 (item.to !== "/" && location.pathname.startsWith(item.to)) ? (
                  <ChevronIcon />
                ) : null}
              </NavLink>
            </li>
          ))}
        </ul>

        {/* Token display + logout */}
        <div className="sidebar-footer">
          <div style={{ marginBottom: "0.25rem" }}>
            Token: {truncatedToken}
          </div>
          <button className="outline" onClick={logout} style={{ width: "100%" }}>
            Logout
          </button>
          <div className="sidebar-footer-version">v2.4.1 — build 20260505</div>
        </div>
      </aside>

      {/* Main area: header + content */}
      <div className="main-area">
        <header className="top-header">
          <div className="top-header-title">
            <PageTitle pathname={location.pathname} />
          </div>
          <div className="top-header-right">
            <div className="top-header-search">
              <SearchIcon />
              Search...
            </div>
            <div className="top-header-user">
              <div className="top-header-user-info">
                <div className="top-header-user-name">Users</div>
                <div className="top-header-user-status">Online · Read Only</div>
              </div>
              <div className="top-header-user-avatar">U</div>
            </div>
            <div className="top-header-clock">
              <ClockIcon />
              <span>14:23:45 KST</span>
            </div>
          </div>
        </header>
        <main className="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
