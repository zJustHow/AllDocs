import { describe, expect, it } from "vitest";
import { isMobileViewport, MOBILE_BREAKPOINT } from "./layout";

describe("layout", () => {
  it("uses a 900px mobile breakpoint", () => {
    expect(MOBILE_BREAKPOINT).toBe(900);
  });

  it("detects mobile viewport widths", () => {
    expect(isMobileViewport(900)).toBe(true);
    expect(isMobileViewport(901)).toBe(false);
  });
});
