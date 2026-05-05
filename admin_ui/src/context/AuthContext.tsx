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
} from "../api/client";

interface AuthContextValue {
  token: string | null;
  isAuthenticated: boolean;
  login: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getStoredToken());

  const logout = useCallback(() => {
    clearStoredToken();
    setToken(null);
  }, []);

  const login = useCallback((newToken: string) => {
    setStoredToken(newToken);
    setToken(newToken);
  }, []);

  // Register global 401 handler
  useEffect(() => {
    setOnUnauthorized(logout);
    return () => setOnUnauthorized(null as any);
  }, [logout]);

  return (
    <AuthContext.Provider
      value={{ token, isAuthenticated: token !== null, login, logout }}
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
