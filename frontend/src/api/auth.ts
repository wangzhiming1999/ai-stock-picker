export interface AuthUser {
  id: string;
  email: string;
}

export interface SigninResult {
  access_token: string;
  refresh_token: string;
  user: AuthUser;
}

export interface SignupResult {
  message?: string;
  user?: AuthUser;
  session?: { access_token: string } | null;
}

const API = "/api";

export async function signin(email: string, password: string): Promise<SigninResult> {
  const res = await fetch(`${API}/auth/signin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "登录失败");
  return data as SigninResult;
}

export async function signup(email: string, password: string): Promise<SignupResult> {
  const res = await fetch(`${API}/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "注册失败");
  return data as SignupResult;
}
