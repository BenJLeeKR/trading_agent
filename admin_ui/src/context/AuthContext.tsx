import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";
import {
  getStoredToken,
  setStoredToken,
  clearStoredToken,
  setOnUnauthorized,
  getAuthMe,
  ApiResponseError,
  UnauthorizedError,
} from "../api/client";

/**
 * 이 배포는 사용자별 계정이 아니라 프로세스 시작 시 설정된 토큰 1개 +
 * 고정 role 1개로 동작한다(`GET /auth/me` 참고). `roleStatus`는 그 role을
 * 확인하는 과정 자체의 상태이고, `role`은 확인에 성공했을 때만 채워진다 —
 * 조회에 실패했을 때 `role`을 임의로 `"admin"`/`"viewer"`로 추정해 채우지
 * 않는다(role 미확인을 admin으로 오인하면 위험한 조작 버튼이 잘못 노출될
 * 수 있다).
 */
export type RoleStatus =
  | "idle" // 토큰 없음 — 로그인 전
  | "loading" // 조회 중
  | "ready" // 조회 성공, role 필드가 유효함
  | "unauthorized" // 401 — 토큰 만료/무효(전역 로그아웃이 함께 처리됨)
  | "forbidden" // 403 — 인증은 됐지만 role이 viewer/admin 둘 다 아님(배포 오류)
  | "error"; // 네트워크/기타 API 실패 — role을 알 수 없음

interface RefreshRoleResult {
  status: RoleStatus;
  role: "viewer" | "admin" | null;
}

interface AuthContextValue {
  token: string | null;
  isAuthenticated: boolean;
  /** 조회에 성공했을 때만 값이 채워진다. 실패/조회 전에는 항상 null이다. */
  role: "viewer" | "admin" | null;
  roleStatus: RoleStatus;
  /** 이 배포가 Bearer 토큰 인증을 강제하는지(`GET /auth/me` 응답 그대로). */
  authEnabled: boolean | null;
  /** role을 마지막으로 확인(성공/실패 불문)한 시각(ISO). 조회 전에는 null. */
  roleCheckedAt: string | null;
  /** 토큰을 저장하고, 곧바로 role을 조회한 결과까지 반환한다(중복 조회를
   * 피하기 위해 로그인 성공 이후의 role 조회는 이 함수 하나로만 한다). */
  login: (token: string) => Promise<RefreshRoleResult>;
  logout: () => void;
  /** role을 다시 조회한다(로그인 직후, 새로고침 직후, 재시도 버튼에서 사용). */
  refreshRole: () => Promise<RefreshRoleResult>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getStoredToken());
  const [role, setRole] = useState<"viewer" | "admin" | null>(null);
  const [roleStatus, setRoleStatus] = useState<RoleStatus>(
    getStoredToken() ? "loading" : "idle",
  );
  const [authEnabled, setAuthEnabled] = useState<boolean | null>(null);
  const [roleCheckedAt, setRoleCheckedAt] = useState<string | null>(null);

  const logout = useCallback(() => {
    clearStoredToken();
    setToken(null);
    setRole(null);
    setRoleStatus("idle");
    setAuthEnabled(null);
    setRoleCheckedAt(null);
  }, []);

  const refreshRole = useCallback(async (): Promise<RefreshRoleResult> => {
    setRoleStatus("loading");
    try {
      const res = await getAuthMe();
      setRole(res.role);
      setAuthEnabled(res.auth_enabled);
      setRoleStatus("ready");
      setRoleCheckedAt(new Date().toISOString());
      return { status: "ready", role: res.role };
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        // request()의 전역 401 핸들러가 이미 logout()을 호출해 token/role
        // 상태를 idle로 초기화했다 — 여기서 다시 덮어쓰지 않는다.
        return { status: "unauthorized", role: null };
      }
      setRole(null);
      setRoleCheckedAt(new Date().toISOString());
      if (err instanceof ApiResponseError && err.status === 403) {
        setRoleStatus("forbidden");
        return { status: "forbidden", role: null };
      }
      setRoleStatus("error");
      return { status: "error", role: null };
    }
  }, []);

  const login = useCallback(
    async (newToken: string): Promise<RefreshRoleResult> => {
      setStoredToken(newToken);
      setToken(newToken);
      // role 조회는 여기서 한 번만 한다 — 마운트 effect(아래)는 "이미 저장된
      // 토큰으로 새로고침한" 경우만 담당하므로 로그인 시점엔 중복 호출이
      // 일어나지 않는다.
      return refreshRole();
    },
    [refreshRole],
  );

  // Register global 401 handler
  useEffect(() => {
    setOnUnauthorized(logout);
    return () => setOnUnauthorized(null as any);
  }, [logout]);

  // 새로고침 직후: 마운트 시점에 이미 저장된 토큰이 있으면 role을 조회한다.
  // 로그인 성공 직후의 조회는 login()이 직접 담당하므로, 여기서는 마운트
  // 시점의 초기 token 값만 확인한다(의도적으로 최초 1회만 실행).
  useEffect(() => {
    if (token) {
      void refreshRole();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AuthContext.Provider
      value={{
        token,
        isAuthenticated: token !== null,
        role,
        roleStatus,
        authEnabled,
        roleCheckedAt,
        login,
        logout,
        refreshRole,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
