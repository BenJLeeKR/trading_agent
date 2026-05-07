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
  it("renders all 6 navigation links and brand", () => {
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
    expect(screen.getByText("Admin Console")).toBeInTheDocument();

    // All 6 nav links (Overview instead of Dashboard in new template)
    expect(screen.getAllByText("Overview")[0]).toBeInTheDocument();
    expect(screen.getByText("Orders")).toBeInTheDocument();
    expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    expect(screen.getByText("Accounts")).toBeInTheDocument();
    expect(screen.getByText("Decisions")).toBeInTheDocument();
    expect(screen.getByText("Agent Runs")).toBeInTheDocument();

    // Outlet content rendered
    expect(screen.getByText("Page Content")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: Read-only badge 표시 (token 유무 관계없이 항상)
 * ─────────────────────────────────────────── */
describe("Layout read-only badge", () => {
  it("shows Read-only badge when token exists", () => {
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

    expect(screen.getByText("Read-only")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: Logout 동작
 * ─────────────────────────────────────────── */
describe("Layout logout", () => {
  it("clears token and shows Read-only badge after logout", async () => {
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

    // Read-only badge is always shown
    expect(screen.getByText("Read-only")).toBeInTheDocument();

    // Click logout button
    await user.click(screen.getByRole("button", { name: /log out/i }));

    // Token cleared from sessionStorage
    expect(sessionStorage.getItem("auth_token")).toBeNull();

    // Read-only badge still shown after logout
    expect(screen.getByText("Read-only")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: Token 없음
 * ─────────────────────────────────────────── */
describe("Layout without token", () => {
  it("shows read-only when no token is available", () => {
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

    // Token display should be "Read-only"
    expect(screen.getByText("Read-only")).toBeInTheDocument();

    // Log Out button should still be present
    expect(screen.getByRole("button", { name: /log out/i })).toBeInTheDocument();
  });
});
