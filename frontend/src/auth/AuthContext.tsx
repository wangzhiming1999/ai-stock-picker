import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { getSupabase } from "../api/supabase";
import { signin, signup, signout } from "../api/auth";
import type { Session } from "@supabase/supabase-js";

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
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function sessionToAuth(s: Session | null): { user: AuthUser | null; token: string | null } {
  if (!s?.user) return { user: null, token: null };
  return {
    user: { id: s.user.id, email: s.user.email ?? "" },
    token: s.access_token ?? null,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ user: AuthUser | null; token: string | null }>(() => ({ user: null, token: null }));
  const [loading, setLoading] = useState(false);

  // 初始化：从 Supabase 恢复 session（cookie + localStorage）
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const sb = await getSupabase();
        const { data } = await sb.auth.getSession();
        if (mounted) setState(sessionToAuth(data.session ?? null));
      } catch {
        /* ignore */
      }
    })();

    // 监听 session 变化（登录/退出/自动 refresh 都会触发）
    const sbPromise = getSupabase();
    let sub: { unsubscribe: () => void } | null = null;
    sbPromise.then((sb) => {
      const { data } = sb.auth.onAuthStateChange((_event, session) => {
        if (mounted) setState(sessionToAuth(session));
      });
      sub = data.subscription;
    });
    return () => {
      mounted = false;
      sub?.unsubscribe();
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    setLoading(true);
    try {
      await signin(email, password);
      // onAuthStateChange 会自动更新 state
    } finally {
      setLoading(false);
    }
  }, []);

  const signUp = useCallback(async (email: string, password: string) => {
    setLoading(true);
    try {
      await signup(email, password);
    } finally {
      setLoading(false);
    }
  }, []);

  const signOut = useCallback(async () => {
    await signout();
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