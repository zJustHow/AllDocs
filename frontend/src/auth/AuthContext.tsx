import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  applyTokenPair,
  fetchCurrentUser,
  loginWithEmail,
  logoutRemote,
  refreshAuthTokens,
  registerWithEmailOtp,
  verifyPhoneOtp,
} from "./api";
import { clearTokens } from "./tokenStore";
import { hasStoredSession } from "./session";
import type { AuthUser, TokenPair } from "./types";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  isAdmin: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, code: string, password: string, displayName?: string) => Promise<void>;
  loginWithPhone: (phone: string, code: string) => Promise<void>;
  completeOAuthLogin: (tokens: TokenPair) => Promise<void>;
  refreshUser: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const bootstrap = useCallback(async () => {
    if (!hasStoredSession()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await fetchCurrentUser();
      setUser(me);
    } catch {
      const refreshed = await refreshAuthTokens();
      if (!refreshed) {
        clearTokens();
        setUser(null);
        setLoading(false);
        return;
      }
      try {
        const me = await fetchCurrentUser(refreshed.access_token);
        setUser(me);
      } catch {
        clearTokens();
        setUser(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await loginWithEmail(email, password);
    const me = await fetchCurrentUser(tokens.access_token);
    setUser(me);
  }, []);

  const register = useCallback(
    async (email: string, code: string, password: string, displayName?: string) => {
      const tokens = await registerWithEmailOtp(email, code, password, displayName);
      const me = await fetchCurrentUser(tokens.access_token);
      setUser(me);
    },
    [],
  );

  const loginWithPhone = useCallback(async (phone: string, code: string) => {
    const tokens = await verifyPhoneOtp(phone, code);
    const me = await fetchCurrentUser(tokens.access_token);
    setUser(me);
  }, []);

  const completeOAuthLogin = useCallback(async (tokens: TokenPair) => {
    const me = await applyTokenPair(tokens);
    setUser(me);
  }, []);

  const refreshUser = useCallback(async () => {
    const me = await fetchCurrentUser();
    setUser(me);
  }, []);

  const logout = useCallback(async () => {
    await logoutRemote();
    setUser(null);
  }, []);

  const value = useMemo(
    (): AuthContextValue => ({
      user,
      loading,
      isAdmin: user?.role === "admin",
      login,
      register,
      loginWithPhone,
      completeOAuthLogin,
      refreshUser,
      logout,
    }),
    [user, loading, login, register, loginWithPhone, completeOAuthLogin, refreshUser, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
