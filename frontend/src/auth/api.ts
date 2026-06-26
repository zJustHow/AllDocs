import { t } from "../i18n";
import type { AuthUser, TokenPair } from "./types";
import { authFetch, authFetchJson } from "./http";
import { authHeaders } from "./session";
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "./tokenStore";

const API_BASE = "";

async function parseError(res: Response): Promise<string> {
  const text = await res.text();
  if (!text) return t("errors.requestFailed");
  try {
    const payload = JSON.parse(text) as { detail?: string | { msg?: string }[] };
    if (typeof payload.detail === "string") return payload.detail;
    if (Array.isArray(payload.detail) && payload.detail[0]?.msg) {
      return payload.detail[0].msg;
    }
  } catch {
    // fall through
  }
  return text;
}

export async function sendPhoneOtp(phone: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/auth/otp/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone }),
  });
  if (!res.ok) throw new Error(await parseError(res));
}

export async function sendRegisterEmailOtp(email: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/auth/register/email-otp/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) throw new Error(await parseError(res));
}

export async function registerWithEmailOtp(
  email: string,
  code: string,
  password: string,
  displayName?: string,
): Promise<TokenPair> {
  const res = await fetch(`${API_BASE}/api/v1/auth/register/email-otp/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      code,
      password,
      display_name: displayName || undefined,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const tokens = (await res.json()) as TokenPair;
  setTokens(tokens.access_token, tokens.refresh_token);
  return tokens;
}

export async function verifyPhoneOtp(phone: string, code: string): Promise<TokenPair> {
  const res = await fetch(`${API_BASE}/api/v1/auth/otp/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone, code }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const tokens = (await res.json()) as TokenPair;
  setTokens(tokens.access_token, tokens.refresh_token);
  return tokens;
}

export function wechatAuthorizeUrl(): string {
  return `${API_BASE}/api/v1/auth/wechat/authorize`;
}

export async function applyTokenPair(tokens: TokenPair): Promise<AuthUser> {
  setTokens(tokens.access_token, tokens.refresh_token);
  return fetchCurrentUser(tokens.access_token);
}

export async function loginWithEmail(email: string, password: string): Promise<TokenPair> {
  const res = await fetch(`${API_BASE}/api/v1/auth/login/email`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const tokens = (await res.json()) as TokenPair;
  setTokens(tokens.access_token, tokens.refresh_token);
  return tokens;
}

export async function registerWithEmail(
  email: string,
  password: string,
  displayName?: string,
): Promise<TokenPair> {
  const res = await fetch(`${API_BASE}/api/v1/auth/register/email`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      password,
      display_name: displayName || undefined,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const tokens = (await res.json()) as TokenPair;
  setTokens(tokens.access_token, tokens.refresh_token);
  return tokens;
}

export async function refreshAuthTokens(): Promise<TokenPair | null> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;
  const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) {
    clearTokens();
    return null;
  }
  const tokens = (await res.json()) as TokenPair;
  setTokens(tokens.access_token, tokens.refresh_token);
  return tokens;
}

export function wechatBindAuthorizeUrl(): string {
  const token = getAccessToken();
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${API_BASE}/api/v1/auth/wechat/bind/authorize${query}`;
}

export async function bindEmail(email: string, password: string): Promise<AuthUser> {
  return authFetchJson<AuthUser>("/api/v1/auth/bind/email", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export async function sendBindPhoneOtp(phone: string): Promise<void> {
  const res = await authFetch("/api/v1/auth/bind/otp/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone }),
  });
  if (!res.ok) throw new Error(await parseError(res));
}

export async function bindPhone(phone: string, code: string): Promise<AuthUser> {
  return authFetchJson<AuthUser>("/api/v1/auth/bind/otp/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone, code }),
  });
}

export type BindProvider = "email" | "phone" | "wechat";

export async function unbindIdentity(provider: BindProvider): Promise<AuthUser> {
  return authFetchJson<AuthUser>(`/api/v1/auth/bind/${provider}`, {
    method: "DELETE",
  });
}

export interface AdminUserItem {
  id: string;
  role: "user" | "admin";
  display_name: string | null;
  email: string | null;
  phone: string | null;
  wechat_bound: boolean;
  is_active: boolean;
  created_at: string;
}

export async function fetchAdminUsers(): Promise<AdminUserItem[]> {
  const payload = await authFetchJson<{ users: AdminUserItem[] }>("/api/v1/admin/users");
  return payload.users;
}

export async function patchAdminUser(
  userId: string,
  body: Partial<Pick<AdminUserItem, "role" | "is_active" | "display_name">>,
): Promise<AdminUserItem> {
  return authFetchJson<AdminUserItem>(`/api/v1/admin/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export interface AdminAuditLogItem {
  id: string;
  action: string;
  actor_user_id: string;
  actor_display_name: string | null;
  target_user_id: string | null;
  target_display_name: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export async function fetchAdminAuditLogs(limit = 50): Promise<AdminAuditLogItem[]> {
  const payload = await authFetchJson<{ logs: AdminAuditLogItem[] }>(
    `/api/v1/admin/audit-logs?limit=${limit}`,
  );
  return payload.logs;
}

export async function fetchCurrentUser(accessToken?: string): Promise<AuthUser> {
  if (accessToken) {
    const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!res.ok) throw new Error(await parseError(res));
    return res.json() as Promise<AuthUser>;
  }
  return authFetchJson<AuthUser>("/api/v1/auth/me");
}

export async function logoutRemote(): Promise<void> {
  const refreshToken = getRefreshToken();
  try {
    await fetch(`${API_BASE}/api/v1/auth/logout`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  } catch {
    // ignore network errors during logout
  }
  clearTokens();
}
