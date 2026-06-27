/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it } from "vitest";
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setTokens,
  withAuthQuery,
} from "./tokenStore";

describe("tokenStore", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("stores, reads, and clears tokens", () => {
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();

    setTokens("access-token", "refresh-token");
    expect(getAccessToken()).toBe("access-token");
    expect(getRefreshToken()).toBe("refresh-token");

    clearTokens();
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
  });

  it("appends auth query param when a token exists", () => {
    expect(withAuthQuery("/api/path")).toBe("/api/path");

    setTokens("my-token", "refresh");
    expect(withAuthQuery("/api/path")).toBe("/api/path?token=my-token");
    expect(withAuthQuery("/api/path?foo=bar")).toBe("/api/path?foo=bar&token=my-token");
  });
});
