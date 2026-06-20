import { afterEach, describe, expect, it, vi } from "vitest";
import { warmPageImage } from "./pageImageCache";

describe("warmPageImage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("preloads each url only once", async () => {
    const created: Array<{ src: string }> = [];
    class MockImage {
      src = "";
      constructor() {
        created.push(this);
      }
    }

    vi.stubGlobal("Image", MockImage);
    const { warmPageImage: warm } = await import("./pageImageCache");

    warm("/page-1.png");
    warm("/page-1.png");
    warm("/page-2.png");

    expect(created).toHaveLength(2);
    expect(created[0]?.src).toBe("/page-1.png");
    expect(created[1]?.src).toBe("/page-2.png");
  });
});
