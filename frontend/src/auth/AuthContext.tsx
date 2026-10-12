import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import * as client from "../api/client";
import type { User } from "../types";

interface AuthContextValue {
  user: User | null;
  token: string | null;
  initializing: boolean;
  /** Set when the session could not be checked for a reason other than an invalid token (e.g. the
   * server is waking up). The token is kept so a retry can restore the session. */
  sessionError: unknown;
  retrySession: () => void;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName: string | null) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => client.getToken());
  const [user, setUser] = useState<User | null>(null);
  const [initializing, setInitializing] = useState<boolean>(() => client.getToken() !== null);
  const [sessionError, setSessionError] = useState<unknown>(null);
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    if (!token || user) {
      setInitializing(false);
      return;
    }
    let cancelled = false;
    setInitializing(true);
    setSessionError(null);
    client
      .me()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (client.parseApiError(err).status === 401) {
          client.clearToken();
          setTokenState(null);
        } else {
          setSessionError(err);
        }
      })
      .finally(() => {
        if (!cancelled) setInitializing(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, user, retryNonce]);

  const retrySession = useCallback(() => setRetryNonce((n) => n + 1), []);

  const login = useCallback(async (email: string, password: string) => {
    const out = await client.login({ email, password });
    client.setToken(out.access_token);
    setUser(out.user);
    setTokenState(out.access_token);
  }, []);

  const register = useCallback(async (email: string, password: string, fullName: string | null) => {
    const out = await client.register({ email, password, full_name: fullName });
    client.setToken(out.access_token);
    setUser(out.user);
    setTokenState(out.access_token);
  }, []);

  const logout = useCallback(() => {
    client.clearToken();
    setUser(null);
    setSessionError(null);
    setTokenState(null);
  }, []);

  const value = useMemo(
    () => ({ user, token, initializing, sessionError, retrySession, login, register, logout }),
    [user, token, initializing, sessionError, retrySession, login, register, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
