/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearTokens, setTokens } from "./tokenStore";

function jsonResponse(body: unknown, ok = true, status = ok ? 200 : 400) {
  return {
    ok,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
}

describe("auth http", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("authFetch attaches bearer token when present", async () => {
    setTokens("access-token", "refresh-token");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    const { authFetch } = await import("./http");
    await authFetch("/api/v1/me");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/me",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer access-token");
  });

  it("authFetch retries once after refreshing on 401", async () => {
    setTokens("expired-access", "refresh-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 401, text: async () => "" })
      .mockResolvedValueOnce(
        jsonResponse({
          access_token: "new-access",
          refresh_token: "new-refresh",
          token_type: "bearer",
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ id: "user-1" }));
    vi.stubGlobal("fetch", fetchMock);

    const { authFetch } = await import("./http");
    const response = await authFetch("/api/v1/me");

    expect(response.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const retryHeaders = fetchMock.mock.calls[2]?.[1]?.headers as Headers;
    expect(retryHeaders.get("Authorization")).toBe("Bearer new-access");
  });

  it("authFetch returns the original 401 when refresh fails", async () => {
    setTokens("expired-access", "refresh-token");
    const unauthorized = { ok: false, status: 401, text: async () => "" };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(unauthorized)
      .mockResolvedValueOnce(jsonResponse({}, false, 401));
    vi.stubGlobal("fetch", fetchMock);

    const { authFetch } = await import("./http");
    const response = await authFetch("/api/v1/me");

    expect(response.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("authFetchJson parses JSON detail errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        text: async () => JSON.stringify({ detail: "Forbidden" }),
      }),
    );

    const { authFetchJson } = await import("./http");
    await expect(authFetchJson("/api/v1/admin/users")).rejects.toThrow("Forbidden");
  });

  it("authFetchJson parses validation error arrays", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        text: async () =>
          JSON.stringify({ detail: [{ msg: "Field required" }] }),
      }),
    );

    const { authFetchJson } = await import("./http");
    await expect(authFetchJson("/api/v1/admin/users")).rejects.toThrow("Field required");
  });

  it("authFetchJson falls back to raw text and default message", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce({
          ok: false,
          text: async () => "plain-text error",
        })
        .mockResolvedValueOnce({
          ok: false,
          text: async () => "",
        }),
    );

    const { authFetchJson } = await import("./http");
    await expect(authFetchJson("/api/v1/admin/users")).rejects.toThrow("plain-text error");
    await expect(authFetchJson("/api/v1/admin/users")).rejects.toThrow(/Request failed|请求失败/i);
  });
});
