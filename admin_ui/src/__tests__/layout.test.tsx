import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, afterEach, vi } from "vitest";
import { Layout } from "../components/Layout";
import { AuthProvider } from "../context/AuthContext";
import { setStoredToken, clearStoredToken } from "../api/client";
import { VALID_TOKEN } from "./test-utils/fixtures";

afterEach(() => {
  vi.restoreAllMocks();
  clearStoredToken();
});

/* ───────────────────────────────────────────
 * Scenario 1: 네비게이션 링크 렌더링
 * ─────────────────────────────────────────── */
describe("Layout navigation", () => {
  it("renders all 5 navigation links and brand", () => {
    setStoredToken(VALID_TOKEN);

    render(
      <MemoryRouter initialEntries={["/"]}>
        <AuthProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<div>Page Content</div>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );

    // Brand
    expect(screen.getByText("AgentTrade")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();

    // All 5 nav links
    expect(screen.getAllByText("Dashboard")[0]).toBeInTheDocument();
    expect(screen.getByText("Orders")).toBeInTheDocument();
    expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    expect(screen.getByText("Accounts")).toBeInTheDocument();
    expect(screen.getByText("Decisions")).toBeInTheDocument();

    // Outlet content rendered
    expect(screen.getByText("Page Content")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: Token 표시
 * ─────────────────────────────────────────── */
describe("Layout token display", () => {
  it("displays truncated token when token exists", () => {
    setStoredToken(VALID_TOKEN);

    render(
      <MemoryRouter initialEntries={["/"]}>
        <AuthProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<div />} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );

    // Token: first 8 characters followed by "..."
    const expectedPrefix = VALID_TOKEN.slice(0, 8);
    expect(screen.getByText(`Token: ${expectedPrefix}...`)).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: Logout 동작
 * ─────────────────────────────────────────── */
describe("Layout logout", () => {
  it("clears token and hides token display on logout", async () => {
    const user = userEvent.setup();
    setStoredToken(VALID_TOKEN);

    render(
      <MemoryRouter initialEntries={["/"]}>
        <AuthProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<div />} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );

    // Verify token is displayed before logout
    const expectedPrefix = VALID_TOKEN.slice(0, 8);
    expect(screen.getByText(`Token: ${expectedPrefix}...`)).toBeInTheDocument();

    // Click logout button
    await user.click(screen.getByRole("button", { name: /logout/i }));

    // Token cleared from sessionStorage
    expect(sessionStorage.getItem("auth_token")).toBeNull();

    // Token display should now show em dash
    expect(screen.getByText("Token: —")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: Token 없음
 * ─────────────────────────────────────────── */
describe("Layout without token", () => {
  it("shows em dash when no token is available", () => {
    // Explicitly ensure no token
    clearStoredToken();

    render(
      <MemoryRouter initialEntries={["/"]}>
        <AuthProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<div />} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );

    // Token display should be em dash
    expect(screen.getByText("Token: —")).toBeInTheDocument();

    // Logout button should still be present
    expect(screen.getByRole("button", { name: /logout/i })).toBeInTheDocument();
  });
});
