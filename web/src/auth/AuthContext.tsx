import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import * as authApi from "../api/auth";
import { ApiError, clearTokens, getAccessToken, setTokens } from "../api/client";
import type { User } from "../types/auth";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  /** Set when startup could not finish for a reason other than "you are logged out" (e.g. offline). */
  bootError: string | null;
  retryBoot: () => void;
  login: (email: string, password: string, otp?: string) => Promise<void>;
  register: (username: string, email: string, password: string, inviteCode?: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [bootError, setBootError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      setBootError(null);
      if (!getAccessToken()) {
        setIsLoading(false);
        return;
      }
      try {
        const me = await authApi.fetchMe();
        if (!cancelled) setUser(me);
      } catch (error) {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          clearTokens(); // the saved login really is no longer valid
        } else if (!cancelled) {
          // The server could not be reached or answered with an error: keep the login, say so,
          // and let the person retry instead of silently signing them out.
          setBootError("Could not reach the server to check your login.");
          return;
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retryBoot = useCallback(() => {
    setIsLoading(true);
    setAttempt((n) => n + 1);
  }, []);

  const login = useCallback(async (email: string, password: string, otp?: string) => {
    const tokens = await authApi.login({ email, password, ...(otp ? { otp } : {}) });
    setTokens(tokens.access_token, tokens.refresh_token);
    const me = await authApi.fetchMe();
    setUser(me);
  }, []);

  const register = useCallback(
    async (username: string, email: string, password: string, inviteCode?: string) => {
      await authApi.register({
        username,
        email,
        password,
        ...(inviteCode ? { invite_code: inviteCode } : {}),
      });
      await login(email, password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // Tokens are stateless (docs/security.md) — even if this network call
      // fails, discarding the local tokens still logs the user out.
    }
    clearTokens();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, isLoading, bootError, retryBoot, login, register, logout }),
    [user, isLoading, bootError, retryBoot, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
