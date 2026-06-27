import { afterEach, describe, expect, it, vi } from "vitest";
import { newId } from "./newId";

describe("newId", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses crypto.randomUUID when available", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "uuid-123" });
    expect(newId()).toBe("uuid-123");
  });

  it("falls back when randomUUID is unavailable", () => {
    vi.stubGlobal("crypto", undefined);
    const id = newId();
    expect(id).toMatch(/^\d+-[a-z0-9]+$/);
  });
});
