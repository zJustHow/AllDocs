import { t } from "../i18n";
import { refreshAuthTokens } from "./api";
import { authHeaders } from "./session";
import { getAccessToken } from "./tokenStore";

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

export async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let res = await fetch(`${API_BASE}${input}`, { ...init, headers });
  if (res.status !== 401) return res;

  const refreshed = await refreshAuthTokens();
  if (!refreshed) return res;

  headers.set("Authorization", `Bearer ${refreshed.access_token}`);
  res = await fetch(`${API_BASE}${input}`, { ...init, headers });
  return res;
}

export async function authFetchJson<T>(input: string, init: RequestInit = {}): Promise<T> {
  const res = await authFetch(input, init);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<T>;
}

export { authHeaders };
