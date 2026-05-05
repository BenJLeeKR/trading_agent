import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard" },
  { to: "/orders", label: "Orders" },
  { to: "/reconciliation", label: "Reconciliation" },
  { to: "/accounts", label: "Accounts" },
  { to: "/decisions", label: "Decisions" },
];

export function Layout() {
  const { token, logout } = useAuth();

  return (
    <div className="app-shell">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-brand-title">🛡️ Admin UI</div>
          <span className="sidebar-brand-badge">READ-ONLY</span>
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
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>

        {/* Token display + logout */}
        <div className="sidebar-footer">
          <div style={{ marginBottom: "0.25rem" }}>
            Token: {token ? `${token.slice(0, 8)}...` : "—"}
          </div>
          <button className="outline" onClick={logout} style={{ width: "100%" }}>
            Logout
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
