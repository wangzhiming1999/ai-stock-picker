import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { signin, signup } from "../api/auth";

export interface AuthUser {
  id: string;
  email: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => void;
}

const TOKEN_KEY = "ai_stock_token";
const USER_KEY = "ai_stock_user";

const AuthContext = createContext<AuthContextValue | null>(null);

function readStored(): { user: AuthUser | null; token: string | null } {
  try {
    const token = localStorage.getItem(TOKEN_KEY);
    const rawUser = localStorage.getItem(USER_KEY);
    return { token, user: rawUser ? (JSON.parse(rawUser) as AuthUser) : null };
  } catch {
    return { user: null, token: null };
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState(readStored);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!state.token) return;
    // 静默校验 token 是否有效 —— 只在明确 401 时清除登录态
    // 避免偶发抖动 / 冷启动 5xx 把用户踢出登录
    fetch("/api/auth/user", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: state.token }),
    })
      .then((res) => {
        if (res.status === 401) {
          localStorage.removeItem(TOKEN_KEY);
          localStorage.removeItem(USER_KEY);
          setState({ user: null, token: null });
        }
        // 200：保持登录；其他（500、网络）：保留登录态等下次再校验
      })
      .catch(() => {
        // 网络错误等：保留登录态，下次刷新再校验
      });
  }, [state.token]);

  const persist = useCallback((user: AuthUser, token: string) => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    setState({ user, token });
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      setLoading(true);
      try {
        const data = await signin(email, password);
        persist(data.user, data.access_token);
      } finally {
        setLoading(false);
      }
    },
    [persist]
  );

  const signUp = useCallback(
    async (email: string, password: string) => {
      setLoading(true);
      try {
        const data = await signup(email, password);
        // 邮箱确认开启时可能没有 session，仅注册成功
        if (data.session?.access_token && data.user) {
          persist(data.user, data.session.access_token);
        }
      } finally {
        setLoading(false);
      }
    },
    [persist]
  );

  const signOut = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setState({ user: null, token: null });
  }, []);

  const value = useMemo(
    () => ({ ...state, loading, signIn, signUp, signOut }),
    [state, loading, signIn, signUp, signOut]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}
