/** 登录/注册：使用 Supabase Auth 客户端，自动管理 cookie/localStorage session + 自动 refresh。 */
import { getSupabase } from "./supabase";

export interface AuthUser {
  id: string;
  email: string;
}

export async function signin(email: string, password: string): Promise<{ access_token: string; user: AuthUser }> {
  const sb = await getSupabase();
  const { data, error } = await sb.auth.signInWithPassword({ email, password });
  if (error) throw new Error(error.message || "登录失败");
  if (!data.session?.access_token || !data.user) throw new Error("登录响应缺失");
  return {
    access_token: data.session.access_token,
    user: { id: data.user.id, email: data.user.email ?? "" },
  };
}

export async function signup(email: string, password: string): Promise<{ message?: string }> {
  const sb = await getSupabase();
  const { data, error } = await sb.auth.signUp({ email, password });
  if (error) throw new Error(error.message || "注册失败");
  // 如果 Supabase 项目关闭了邮箱确认，signUp 会自动建立 session
  return { message: data.session ? "注册成功" : "注册成功，请检查邮箱完成确认" };
}

export async function signout(): Promise<void> {
  const sb = await getSupabase();
  await sb.auth.signOut();
}