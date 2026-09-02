/** Supabase Auth 客户端：自动管理 session（cookie + localStorage）+ 自动 refresh token。 */
import { createClient, type SupabaseClient, type Session } from "@supabase/supabase-js";

let _client: SupabaseClient | null = null;
let _initPromise: Promise<SupabaseClient> | null = null;

async function initClient(): Promise<SupabaseClient> {
  if (_client) return _client;
  if (_initPromise) return _initPromise;
  _initPromise = (async () => {
    const res = await fetch("/api/auth/config");
    if (!res.ok) throw new Error("获取 Supabase 配置失败");
    const { supabase_url, anon_key } = await res.json();
    _client = createClient(supabase_url, anon_key, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: false,
        // 使用 supabase 默认 storage key（sb-{ref}-auth-token）便于兼容
      },
    });
    return _client;
  })();
  return _initPromise;
}

export async function getSupabase(): Promise<SupabaseClient> {
  return initClient();
}

export function getCachedSession(): Session | null {
  // 同步从 localStorage 读取 session（避免每次都 await 初始化）
  if (!_client) {
    try {
      const raw = localStorage.getItem("ai_stock_auth");
      if (!raw) return null;
      // supabase-js 用 sb-{key}-auth-token 单 key；这里偷懒读我们存的 ai_stock_auth（supabase-js 内部格式）
      const parsed = JSON.parse(raw);
      // 不同 supabase-js 版本 storage key 不同；fallback 扫描所有 supabase key
      if (!parsed?.access_token) {
        for (let i = 0; i < localStorage.length; i++) {
          const k = localStorage.key(i);
          if (k && k.startsWith("sb-") && k.endsWith("-auth-token")) {
            const v = JSON.parse(localStorage.getItem(k) || "{}");
            if (v?.access_token) return v as Session;
          }
        }
        return null;
      }
      return parsed as Session;
    } catch {
      return null;
    }
  }
  return _client.auth.getSession().then((r) => r.data.session ?? null) as unknown as Session | null;
}

export async function getSession(): Promise<Session | null> {
  const sb = await initClient();
  const { data } = await sb.auth.getSession();
  return data.session ?? null;
}