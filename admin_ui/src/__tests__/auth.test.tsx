import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { describe, expect, it, afterEach, vi } from "vitest";
import { LoginForm } from "../components/LoginForm";
import { ProtectedRoute } from "../components/ProtectedRoute";
import { AuthProvider, useAuth } from "../context/AuthContext";
import { API_BASE_URL, setStoredToken, clearStoredToken } from "../api/client";
import { mockFetchOnce, mockFetchError, mockFetchNetworkError } from "./test-utils/mockFetch";
import { VALID_TOKEN } from "./test-utils/fixtures";

afterEach(() => {
  vi.restoreAllMocks();
});

/* ───────────────────────────────────────────
 * Scenario 1: LoginForm 기본 렌더링
 * ─────────────────────────────────────────── */
describe("LoginForm rendering", () => {
  it("renders title, password input, and submit button", () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginForm />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(screen.getByText("운영 콘솔")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("토큰을 붙여넣으세요...")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /대시보드 접속/i })).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: 빈 token → 버튼 disabled (제출 불가)
 * ─────────────────────────────────────────── */
describe("LoginForm empty token", () => {
  it("disables submit button when input is empty", () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginForm />
        </AuthProvider>
      </MemoryRouter>,
    );

    const button = screen.getByRole("button", { name: /대시보드 접속/i });
    expect(button).toBeDisabled();
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: 유효한 token → login 성공
 * ─────────────────────────────────────────── */
describe("LoginForm valid token", () => {
  it("stores token and authenticates on valid response", async () => {
    const user = userEvent.setup();
    const fetchSpy = mockFetchOnce({ status: "ok" }); // GET /orders returns 200

    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginForm />
        </AuthProvider>
      </MemoryRouter>,
    );

    await user.type(screen.getByPlaceholderText("토큰을 붙여넣으세요..."), VALID_TOKEN);
    await user.click(screen.getByRole("button", { name: /대시보드 접속/i }));

    // Wait for async verification
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(`${API_BASE_URL}/orders`, {
        headers: { Authorization: `Bearer ${VALID_TOKEN}` },
      });
    });

    // Token stored in sessionStorage (key from client.ts: TOKEN_KEY = "auth_token")
    expect(sessionStorage.getItem("auth_token")).toBe(VALID_TOKEN);
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: 잘못된 token → 401 에러
 * ─────────────────────────────────────────── */
describe("LoginForm invalid token", () => {
  it("shows error on 401 response", async () => {
    const user = userEvent.setup();
    mockFetchError(401, "Unauthorized");

    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginForm />
        </AuthProvider>
      </MemoryRouter>,
    );

    await user.type(screen.getByPlaceholderText("토큰을 붙여넣으세요..."), "bad-token");
    await user.click(screen.getByRole("button", { name: /대시보드 접속/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/유효하지 않은 토큰/i),
      ).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: 네트워크 오류
 * ─────────────────────────────────────────── */
describe("LoginForm network error", () => {
  it("shows connection error on network failure", async () => {
    const user = userEvent.setup();
    mockFetchNetworkError();

    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginForm />
        </AuthProvider>
      </MemoryRouter>,
    );

    await user.type(screen.getByPlaceholderText("토큰을 붙여넣으세요..."), VALID_TOKEN);
    await user.click(screen.getByRole("button", { name: /대시보드 접속/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/서버에 연결할 수 없습니다/i),
      ).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: 기존 sessionStorage token → protected 진입
 * ─────────────────────────────────────────── */
describe("ProtectedRoute with existing token", () => {
  it("renders children when token exists in sessionStorage", () => {
    // Pre-set token in sessionStorage before component mounts
    setStoredToken(VALID_TOKEN);

    render(
      <MemoryRouter initialEntries={["/"]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<div>Login Page</div>} />
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <div>Protected Content</div>
                </ProtectedRoute>
              }
            />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );

    // Protected content should be rendered, not redirected to /login
    expect(screen.getByText("Protected Content")).toBeInTheDocument();
    expect(screen.queryByText("Login Page")).not.toBeInTheDocument();

    // Cleanup
    clearStoredToken();
  });
});

/* ───────────────────────────────────────────
 * Scenario 7: Login → token 저장 확인 (navigate 없이도 auth state 전환)
 * ─────────────────────────────────────────── */
describe("Login flow → auth state change", () => {
  it("updates auth state after successful login", async () => {
    const user = userEvent.setup();
    mockFetchOnce({ status: "ok" }); // GET /orders returns 200

    function AuthStateDisplay() {
      const { isAuthenticated, token } = useAuth();
      return (
        <div>
          <span data-testid="auth-status">
            {isAuthenticated ? "Authenticated" : "Not Authenticated"}
          </span>
          <span data-testid="token-value">{token ?? "null"}</span>
        </div>
      );
    }

    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginForm />
          <AuthStateDisplay />
        </AuthProvider>
      </MemoryRouter>,
    );

    // Submit valid token
    await user.type(screen.getByPlaceholderText("토큰을 붙여넣으세요..."), VALID_TOKEN);
    await user.click(screen.getByRole("button", { name: /대시보드 접속/i }));

    // Wait for auth state to update (login() was called after fetch success)
    await waitFor(() => {
      expect(screen.getByTestId("auth-status")).toHaveTextContent("Authenticated");
    });

    // Token is stored in sessionStorage
    expect(sessionStorage.getItem("auth_token")).toBe(VALID_TOKEN);
  });
});

/* ───────────────────────────────────────────
 * Scenario 8: Logout → token 제거
 * ─────────────────────────────────────────── */
describe("Logout", () => {
  it("clears token and auth state on logout", async () => {
    const user = userEvent.setup();

    // Pre-set token
    setStoredToken(VALID_TOKEN);

    function LogoutTestComponent() {
      const { isAuthenticated, logout, token } = useAuth();
      return (
        <div>
          <span data-testid="auth-status">
            {isAuthenticated ? "Authenticated" : "Not Authenticated"}
          </span>
          <span data-testid="token-value">{token ?? "null"}</span>
          <button onClick={logout}>로그아웃</button>
        </div>
      );
    }

    render(
      <MemoryRouter>
        <AuthProvider>
          <LogoutTestComponent />
        </AuthProvider>
      </MemoryRouter>,
    );

    // Initially authenticated
    expect(screen.getByTestId("auth-status")).toHaveTextContent("Authenticated");
    expect(screen.getByTestId("token-value")).toHaveTextContent(VALID_TOKEN);

    // Click logout
    await user.click(screen.getByRole("button", { name: /로그아웃/i }));

    // Token cleared from sessionStorage and state
    expect(screen.getByTestId("auth-status")).toHaveTextContent("Not Authenticated");
    expect(screen.getByTestId("token-value")).toHaveTextContent("null");
    expect(sessionStorage.getItem("auth_token")).toBeNull();

    // Cleanup
    clearStoredToken();
  });
});
