/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it } from "vitest";
import { authHeaders, hasStoredSession } from "./session";
import { clearTokens, setTokens } from "./tokenStore";

describe("session", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("reports no stored session without tokens", () => {
    expect(hasStoredSession()).toBe(false);
    expect(authHeaders()).toEqual({});
  });

  it("reports a stored session when both tokens exist", () => {
    setTokens("access-token", "refresh-token");
    expect(hasStoredSession()).toBe(true);
    expect(authHeaders()).toEqual({ Authorization: "Bearer access-token" });
  });

  it("treats partial tokens as no session", () => {
    setTokens("access-only", "refresh-token");
    clearTokens();
    localStorage.setItem("alldocs_access_token", "access-only");
    expect(hasStoredSession()).toBe(false);
  });
});
