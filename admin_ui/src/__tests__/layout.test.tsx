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
  it("renders all 8 navigation links and brand", () => {
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
    expect(screen.getByText("운영 콘솔")).toBeInTheDocument();

    // All nav links (운영 모니터링 4 + 기본 운영 4)
    expect(screen.getByText("운영 대시보드")).toBeInTheDocument();
    expect(screen.getByText("운영 경고")).toBeInTheDocument();
    expect(screen.getByText("주문 추적")).toBeInTheDocument();
    expect(screen.getByText("정합성 점검")).toBeInTheDocument();
    expect(screen.getByText("현재가")).toBeInTheDocument();
    expect(screen.getByText("주문내역")).toBeInTheDocument();
    expect(screen.getByText("계좌")).toBeInTheDocument();
    expect(screen.getByText("의사결정")).toBeInTheDocument();
    expect(screen.getByText("에이전트 실행")).toBeInTheDocument();

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

    expect(screen.getByText("읽기 전용")).toBeInTheDocument();
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
    expect(screen.getByText("읽기 전용")).toBeInTheDocument();

    // Click logout button
    await user.click(screen.getByRole("button", { name: /로그아웃/i }));

    // Token cleared from sessionStorage
    expect(sessionStorage.getItem("auth_token")).toBeNull();

    // Read-only badge still shown after logout
    expect(screen.getByText("읽기 전용")).toBeInTheDocument();
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
    expect(screen.getByText("읽기 전용")).toBeInTheDocument();

    // Log Out button should still be present
    expect(screen.getByRole("button", { name: /로그아웃/i })).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: 모바일 삼선 메뉴
 * ─────────────────────────────────────────── */
describe("Layout mobile menu", () => {
  it("opens the dropdown on hamburger click and closes it again on a second click", async () => {
    const user = userEvent.setup();
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

    // Closed by default — only the desktop sidebar's nav items exist.
    expect(screen.getAllByText("현재가")).toHaveLength(1);

    const toggle = screen.getByRole("button", { name: "메뉴 열기" });
    await user.click(toggle);

    // Open — the mobile dropdown renders a second copy of the nav list.
    expect(screen.getAllByText("현재가")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "메뉴 닫기" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "메뉴 닫기" }));
    expect(screen.getAllByText("현재가")).toHaveLength(1);
  });

  it("closes the dropdown after clicking a nav item", async () => {
    const user = userEvent.setup();
    setStoredToken(VALID_TOKEN);

    render(
      <MemoryRouter initialEntries={["/"]}>
        <AuthProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<div>Page Content</div>} />
              <Route path="/accounts" element={<div>Accounts Page</div>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("button", { name: "메뉴 열기" }));
    expect(screen.getAllByText("계좌")).toHaveLength(2);

    // Click the mobile dropdown's copy of the "계좌" link (the last one rendered).
    const accountLinks = screen.getAllByText("계좌");
    await user.click(accountLinks[accountLinks.length - 1]);

    await screen.findByText("Accounts Page");
    expect(screen.getAllByText("계좌")).toHaveLength(1);
  });
});
