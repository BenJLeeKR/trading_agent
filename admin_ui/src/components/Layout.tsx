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
    <div style={{ display: "flex", minHeight: "100vh" }}>
      {/* Sidebar */}
      <nav
        style={{
          width: "220px",
          padding: "1rem",
          borderRight: "1px solid var(--pico-muted-border-color, #333)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ marginBottom: "1.5rem" }}>
          <strong style={{ fontSize: "1.1rem" }}>🛡️ Admin UI</strong>
          <br />
          <span
            style={{
              fontSize: "0.75rem",
              color: "var(--pico-muted-color)",
              backgroundColor: "var(--pico-ins-color)",
              padding: "0.1rem 0.4rem",
              borderRadius: "3px",
              fontWeight: 600,
            }}
          >
            READ-ONLY
          </span>
        </div>

        <ul style={{ listStyle: "none", padding: 0, margin: 0, flex: 1 }}>
          {NAV_ITEMS.map((item) => (
            <li key={item.to} style={{ marginBottom: "0.25rem" }}>
              <NavLink
                to={item.to}
                end={item.to === "/"}
                style={({ isActive }) => ({
                  display: "block",
                  padding: "0.4rem 0.75rem",
                  borderRadius: "4px",
                  textDecoration: "none",
                  color: isActive
                    ? "var(--pico-primary-inverse)"
                    : "var(--pico-color)",
                  backgroundColor: isActive
                    ? "var(--pico-primary)"
                    : "transparent",
                })}
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>

        {/* Token display + logout */}
        <div
          style={{
            fontSize: "0.75rem",
            color: "var(--pico-muted-color)",
            wordBreak: "break-all",
          }}
        >
          <div style={{ marginBottom: "0.25rem" }}>
            Token: {token ? `${token.slice(0, 8)}...` : "—"}
          </div>
          <button className="outline" onClick={logout} style={{ width: "100%" }}>
            Logout
          </button>
        </div>
      </nav>

      {/* Main content */}
      <main style={{ flex: 1, padding: "1.5rem", overflow: "auto" }}>
        <Outlet />
      </main>
    </div>
  );
}
