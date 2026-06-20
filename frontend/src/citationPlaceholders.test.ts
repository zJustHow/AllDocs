import { describe, expect, it } from "vitest";
import {
  citationPlaceholder,
  hasCitationPlaceholders,
} from "./citationPlaceholders";

describe("citationPlaceholder", () => {
  it("wraps index in private-use delimiter characters", () => {
    const placeholder = citationPlaceholder(3);
    expect(placeholder).toContain("3");
    expect(hasCitationPlaceholders(placeholder)).toBe(true);
  });
});

describe("hasCitationPlaceholders", () => {
  it("detects placeholder markers in content", () => {
    expect(hasCitationPlaceholders(`before ${citationPlaceholder(0)} after`)).toBe(true);
    expect(hasCitationPlaceholders("plain markdown")).toBe(false);
  });
});
