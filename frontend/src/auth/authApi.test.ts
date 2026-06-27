/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthUser, TokenPair } from "./types";
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "./tokenStore";

const sampleUser: AuthUser = {
  id: "user-1",
  role: "user",
  display_name: "Test User",
  email: "user@test.com",
  phone: null,
  wechat_bound: false,
};

const sampleTokens: TokenPair = {
  access_token: "access-token",
  refresh_token: "refresh-token",
  token_type: "bearer",
};

function jsonResponse(body: unknown, ok = true, status = ok ? 200 : 400) {
  return {
    ok,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
}

describe("auth api", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends phone and email OTP requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    const { sendPhoneOtp, sendRegisterEmailOtp } = await import("./api");

    await sendPhoneOtp("+8613800138000");
    await sendRegisterEmailOtp("user@test.com");

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/auth/otp/send", expect.any(Object));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/register/email-otp/send",
      expect.any(Object),
    );
  });

  it("registers and verifies OTP flows while storing tokens", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(sampleTokens));
    vi.stubGlobal("fetch", fetchMock);

    const { registerWithEmailOtp, verifyPhoneOtp } = await import("./api");

    await registerWithEmailOtp("user@test.com", "123456", "password123", "Test");
    expect(getAccessToken()).toBe("access-token");

    clearTokens();
    await verifyPhoneOtp("+8613800138000", "654321");
    expect(getRefreshToken()).toBe("refresh-token");
  });

  it("logs in with email and password", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(sampleTokens)));

    const { loginWithEmail } = await import("./api");
    const tokens = await loginWithEmail("user@test.com", "password123");

    expect(tokens.access_token).toBe("access-token");
    expect(getAccessToken()).toBe("access-token");
  });

  it("registers with email and password", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(sampleTokens)));

    const { registerWithEmail } = await import("./api");
    await registerWithEmail("user@test.com", "password123", "Test User");
    expect(getAccessToken()).toBe("access-token");
  });

  it("builds WeChat authorize URLs", async () => {
    const { wechatAuthorizeUrl, wechatBindAuthorizeUrl } = await import("./api");
    expect(wechatAuthorizeUrl()).toBe("/api/v1/auth/wechat/authorize");
    expect(wechatBindAuthorizeUrl()).toBe("/api/v1/auth/wechat/bind/authorize");

    setTokens("bind-token", "refresh");
    expect(wechatBindAuthorizeUrl()).toBe(
      "/api/v1/auth/wechat/bind/authorize?token=bind-token",
    );
  });

  it("applies token pairs and fetches the current user", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(sampleUser)),
    );

    const { applyTokenPair, fetchCurrentUser } = await import("./api");
    const user = await applyTokenPair(sampleTokens);
    expect(user).toEqual(sampleUser);

    const me = await fetchCurrentUser("explicit-token");
    expect(me).toEqual(sampleUser);
  });

  it("refreshes tokens and clears them on failure", async () => {
    setTokens("old-access", "old-refresh");

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(sampleTokens))
      .mockResolvedValueOnce(jsonResponse({}, false, 401));
    vi.stubGlobal("fetch", fetchMock);

    const { refreshAuthTokens } = await import("./api");

    await expect(refreshAuthTokens()).resolves.toEqual(sampleTokens);

    setTokens("old-access", "old-refresh");
    await expect(refreshAuthTokens()).resolves.toBeNull();
    expect(getAccessToken()).toBeNull();
  });

  it("returns null when refresh is requested without a refresh token", async () => {
    const { refreshAuthTokens } = await import("./api");
    await expect(refreshAuthTokens()).resolves.toBeNull();
  });

  it("binds and unbinds identities via authenticated requests", async () => {
    setTokens("access-token", "refresh-token");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(sampleUser));
    vi.stubGlobal("fetch", fetchMock);

    const { bindEmail, bindPhone, sendBindPhoneOtp, unbindIdentity } = await import("./api");

    await bindEmail("user@test.com", "password123");
    await sendBindPhoneOtp("+8613800138000");
    await bindPhone("+8613800138000", "123456");
    await unbindIdentity("email");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/bind/email",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/bind/otp/send",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/bind/otp/verify",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/bind/email",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("retries authenticated requests after a 401 refresh", async () => {
    setTokens("expired-access", "refresh-token");

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 401, text: async () => "" })
      .mockResolvedValueOnce(jsonResponse(sampleTokens))
      .mockResolvedValueOnce(jsonResponse(sampleUser));
    vi.stubGlobal("fetch", fetchMock);

    const { fetchCurrentUser } = await import("./api");
    await expect(fetchCurrentUser()).resolves.toEqual(sampleUser);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("parses API errors from JSON detail payloads", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        text: async () => JSON.stringify({ detail: "Invalid credentials" }),
      }),
    );

    const { loginWithEmail } = await import("./api");
    await expect(loginWithEmail("user@test.com", "bad")).rejects.toThrow(
      "Invalid credentials",
    );
  });

  it("parses validation error arrays", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        text: async () =>
          JSON.stringify({ detail: [{ msg: "Email already registered" }] }),
      }),
    );

    const { sendRegisterEmailOtp } = await import("./api");
    await expect(sendRegisterEmailOtp("user@test.com")).rejects.toThrow(
      "Email already registered",
    );
  });

  it("logs out remotely and clears tokens even when the request fails", async () => {
    setTokens("access-token", "refresh-token");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));

    const { logoutRemote } = await import("./api");
    await logoutRemote();
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
  });

  it("fetches admin users and audit logs", async () => {
    setTokens("access-token", "refresh-token");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({ users: [{ id: "user-1" }] }))
        .mockResolvedValueOnce(jsonResponse({ logs: [{ id: "log-1" }] })),
    );

    const { fetchAdminUsers, fetchAdminAuditLogs } = await import("./api");
    await expect(fetchAdminUsers()).resolves.toEqual([{ id: "user-1" }]);
    await expect(fetchAdminAuditLogs(25)).resolves.toEqual([{ id: "log-1" }]);
  });
});
