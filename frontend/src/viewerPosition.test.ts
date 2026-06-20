import { describe, expect, it, vi } from "vitest";
import {
  bboxToOverlayStyle,
  highlightRegionsKey,
  isValidBbox,
  resolveHighlightRegions,
  scrollToPageElement,
  scrollToPageRegion,
} from "./viewerPosition";

function mockImage(overrides: Partial<HTMLImageElement> = {}): HTMLImageElement {
  return {
    offsetWidth: 400,
    offsetHeight: 600,
    naturalWidth: 800,
    naturalHeight: 1200,
    complete: true,
    ...overrides,
  } as HTMLImageElement;
}

describe("isValidBbox", () => {
  it("accepts four finite numbers", () => {
    expect(isValidBbox([0, 0.1, 0.5, 0.9])).toBe(true);
  });

  it("rejects invalid bbox values", () => {
    expect(isValidBbox(null)).toBe(false);
    expect(isValidBbox([0, 1, 2])).toBe(false);
    expect(isValidBbox([0, 1, NaN, 3])).toBe(false);
  });
});

describe("resolveHighlightRegions", () => {
  it("filters out regions with invalid page or bbox", () => {
    const regions = resolveHighlightRegions({
      regions: [
        { page: 1, bbox: [0, 0, 1, 1] },
        { page: NaN, bbox: [0, 0, 1, 1] },
        { page: 2, bbox: [0, 0] as unknown as [number, number, number, number] },
      ],
    });

    expect(regions).toEqual([{ page: 1, bbox: [0, 0, 1, 1] }]);
  });
});

describe("highlightRegionsKey", () => {
  it("builds a stable key from page and bbox coordinates", () => {
    const key = highlightRegionsKey([
      { page: 1, bbox: [0.1, 0.2, 0.3, 0.4] },
      { page: 2, bbox: [0, 0, 1, 1] },
    ]);

    expect(key).toBe("1:0.1,0.2,0.3,0.4|2:0,0,1,1");
  });
});

describe("bboxToOverlayStyle", () => {
  it("maps normalized bbox coordinates to pixel overlay styles", () => {
    const style = bboxToOverlayStyle([0.1, 0.2, 0.3, 0.4], mockImage(), 2);

    expect(style).toEqual({
      top: "120px",
      left: "40px",
      width: "80px",
      height: "120px",
    });
  });

  it("maps absolute PDF bbox coordinates using render scale", () => {
    const style = bboxToOverlayStyle([100, 200, 300, 400], mockImage(), 2);

    expect(style.left).toBe("100px");
    expect(style.top).toBe("200px");
    expect(style.width).toBe("200px");
    expect(style.height).toBe("200px");
  });

  it("enforces a minimum overlay size", () => {
    const style = bboxToOverlayStyle([0.49, 0.49, 0.501, 0.501], mockImage(), 2);
    expect(Number.parseFloat(style.width)).toBeGreaterThanOrEqual(4);
    expect(Number.parseFloat(style.height)).toBeGreaterThanOrEqual(4);
  });
});

describe("scroll helpers", () => {
  it("scrolls to page top with padding", () => {
    const scrollEl = {
      scrollTo: vi.fn(),
    } as unknown as HTMLElement;
    const pageEl = { offsetTop: 240 } as HTMLElement;

    scrollToPageElement(scrollEl, pageEl, "auto");

    expect(scrollEl.scrollTo).toHaveBeenCalledWith({ top: 224, behavior: "auto" });
  });

  it("scrolls to page element when bbox is invalid", () => {
    const scrollEl = {
      clientHeight: 800,
      scrollTo: vi.fn(),
    } as unknown as HTMLElement;
    const pageEl = {
      offsetTop: 100,
      querySelector: vi.fn().mockReturnValue(mockImage()),
    } as unknown as HTMLElement;

    const scrolled = scrollToPageRegion(scrollEl, pageEl, null, 2, "smooth");

    expect(scrolled).toBe(true);
    expect(scrollEl.scrollTo).toHaveBeenCalledWith({ top: 84, behavior: "smooth" });
  });

  it("returns false when page image is not ready", () => {
    const scrollEl = { scrollTo: vi.fn() } as unknown as HTMLElement;
    const pageEl = {
      querySelector: vi.fn().mockReturnValue(
        mockImage({ complete: false, naturalWidth: 0 }),
      ),
    } as unknown as HTMLElement;

    expect(scrollToPageRegion(scrollEl, pageEl, [0, 0, 1, 1], 2, "auto")).toBe(false);
  });
});
