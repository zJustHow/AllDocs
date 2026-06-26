import { getAccessToken, getRefreshToken } from "./tokenStore";

export function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

export function hasStoredSession(): boolean {
  return Boolean(getAccessToken() && getRefreshToken());
}
