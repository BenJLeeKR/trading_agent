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
    mockFetchOnce({ role: "viewer", auth_enabled: true }); // GET /auth/me (login 직후 role 조회)

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
  it("renders children when token exists in sessionStorage", async () => {
    // Pre-set token in sessionStorage before component mounts
    setStoredToken(VALID_TOKEN);
    // AuthProvider 마운트 시 저장된 토큰이 있으면 role을 다시 조회한다 —
    // 이 화면 자체와는 무관하지만 그 fetch를 mock해두지 않으면 실제 네트워크
    // 호출이 발생한다.
    const fetchSpy = mockFetchOnce({ role: "viewer", auth_enabled: true });

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

    // 마운트 시 발생하는 role 조회가 끝날 때까지 기다려 act() 경고 없이
    // 테스트를 종료한다.
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());

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
    mockFetchOnce({ role: "viewer", auth_enabled: true }); // GET /auth/me (login 직후 role 조회)

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
    // AuthProvider 마운트 시 저장된 토큰이 있으면 role을 다시 조회한다.
    mockFetchOnce({ role: "viewer", auth_enabled: true });

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

/* ───────────────────────────────────────────
 * Scenario 9: role 조회 — viewer/admin/실패 상태 구분
 * ─────────────────────────────────────────── */
function RoleStateDisplay() {
  const { role, roleStatus, authEnabled } = useAuth();
  return (
    <div>
      <span data-testid="role-value">{role ?? "null"}</span>
      <span data-testid="role-status">{roleStatus}</span>
      <span data-testid="auth-enabled-value">{String(authEnabled)}</span>
    </div>
  );
}

describe("Login flow → role(viewer/admin) 조회", () => {
  it("viewer role 응답이면 role이 정확히 viewer로 표시된다", async () => {
    const user = userEvent.setup();
    mockFetchOnce({ status: "ok" }); // GET /orders
    mockFetchOnce({ role: "viewer", auth_enabled: true }); // GET /auth/me

    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginForm />
          <RoleStateDisplay />
        </AuthProvider>
      </MemoryRouter>,
    );

    await user.type(screen.getByPlaceholderText("토큰을 붙여넣으세요..."), VALID_TOKEN);
    await user.click(screen.getByRole("button", { name: /대시보드 접속/i }));

    await waitFor(() => {
      expect(screen.getByTestId("role-status")).toHaveTextContent("ready");
    });
    expect(screen.getByTestId("role-value")).toHaveTextContent("viewer");
    expect(screen.getByTestId("auth-enabled-value")).toHaveTextContent("true");
  });

  it("admin role 응답이면 role이 정확히 admin으로 표시된다(viewer와 갈림)", async () => {
    const user = userEvent.setup();
    mockFetchOnce({ status: "ok" }); // GET /orders
    mockFetchOnce({ role: "admin", auth_enabled: true }); // GET /auth/me

    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginForm />
          <RoleStateDisplay />
        </AuthProvider>
      </MemoryRouter>,
    );

    await user.type(screen.getByPlaceholderText("토큰을 붙여넣으세요..."), VALID_TOKEN);
    await user.click(screen.getByRole("button", { name: /대시보드 접속/i }));

    await waitFor(() => {
      expect(screen.getByTestId("role-status")).toHaveTextContent("ready");
    });
    expect(screen.getByTestId("role-value")).toHaveTextContent("admin");
  });

  it("role 조회가 403(forbidden)이면 role이 admin으로 대체되지 않고 null로 남는다", async () => {
    const user = userEvent.setup();
    mockFetchOnce({ status: "ok" }); // GET /orders — 토큰 자체는 유효
    mockFetchError(403, "Insufficient permissions — viewer role required"); // GET /auth/me

    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginForm />
          <RoleStateDisplay />
        </AuthProvider>
      </MemoryRouter>,
    );

    await user.type(screen.getByPlaceholderText("토큰을 붙여넣으세요..."), VALID_TOKEN);
    await user.click(screen.getByRole("button", { name: /대시보드 접속/i }));

    await waitFor(() => {
      expect(screen.getByTestId("role-status")).toHaveTextContent("forbidden");
    });
    // 조회 실패를 admin/viewer 어느 쪽으로도 조용히 대체하지 않는다.
    expect(screen.getByTestId("role-value")).toHaveTextContent("null");
  });

  it("role 조회가 네트워크 오류면 role이 admin으로 대체되지 않고 error 상태가 된다", async () => {
    const user = userEvent.setup();
    mockFetchOnce({ status: "ok" }); // GET /orders
    mockFetchNetworkError(); // GET /auth/me

    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginForm />
          <RoleStateDisplay />
        </AuthProvider>
      </MemoryRouter>,
    );

    await user.type(screen.getByPlaceholderText("토큰을 붙여넣으세요..."), VALID_TOKEN);
    await user.click(screen.getByRole("button", { name: /대시보드 접속/i }));

    await waitFor(() => {
      expect(screen.getByTestId("role-status")).toHaveTextContent("error");
    });
    expect(screen.getByTestId("role-value")).toHaveTextContent("null");
  });

  it("role 조회가 401이면 로그인 화면에 명확한 오류를 보여주고 대시보드로 넘어가지 않는다", async () => {
    const user = userEvent.setup();
    mockFetchOnce({ status: "ok" }); // GET /orders — 방금 검증은 성공
    mockFetchError(401, "Unauthorized"); // GET /auth/me — 곧바로 401(레이스/무효화 시나리오)

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
      expect(screen.getByText(/다시 시도해주세요/)).toBeInTheDocument();
    });
    // 로그인 화면이 그대로 남아있어야 한다(다른 화면으로 넘어가지 않음).
    expect(screen.getByPlaceholderText("토큰을 붙여넣으세요...")).toBeInTheDocument();
  });
});
