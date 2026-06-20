export type Bbox = [number, number, number, number];

export interface BboxRegion {
  page: number;
  bbox: Bbox;
}

export function isValidBbox(bbox: number[] | null | undefined): bbox is Bbox {
  return (
    Array.isArray(bbox) && bbox.length === 4 && bbox.every(Number.isFinite)
  );
}

export function resolveHighlightRegions(target: {
  regions: BboxRegion[];
}): BboxRegion[] {
  return target.regions.filter(
    (region): region is BboxRegion =>
      Number.isFinite(region.page) && isValidBbox(region.bbox),
  );
}

export function highlightRegionsKey(regions: BboxRegion[]): string {
  return regions
    .map((region) => `${region.page}:${region.bbox.join(",")}`)
    .join("|");
}

function isNormalizedBbox(bbox: Bbox): boolean {
  return bbox.every((value) => value >= 0 && value <= 1.001);
}

export function bboxToOverlayStyle(
  bbox: Bbox,
  img: HTMLImageElement,
  renderScale: number,
): { top: string; left: string; width: string; height: string } {
  let top: number;
  let left: number;
  let width: number;
  let height: number;

  if (isNormalizedBbox(bbox)) {
    top = bbox[1] * img.offsetHeight;
    left = bbox[0] * img.offsetWidth;
    width = (bbox[2] - bbox[0]) * img.offsetWidth;
    height = (bbox[3] - bbox[1]) * img.offsetHeight;
  } else {
    const pdfWidth = img.naturalWidth / renderScale;
    const pdfHeight = img.naturalHeight / renderScale;
    left = (bbox[0] / pdfWidth) * img.offsetWidth;
    top = (bbox[1] / pdfHeight) * img.offsetHeight;
    width = ((bbox[2] - bbox[0]) / pdfWidth) * img.offsetWidth;
    height = ((bbox[3] - bbox[1]) / pdfHeight) * img.offsetHeight;
  }

  return {
    top: `${top}px`,
    left: `${left}px`,
    width: `${Math.max(width, 4)}px`,
    height: `${Math.max(height, 4)}px`,
  };
}

export function resolvePageScrollTop(pageEl: HTMLElement): number {
  const offset = pageEl.dataset?.pageOffset;
  if (offset !== undefined) {
    const parsed = Number.parseFloat(offset);
    if (Number.isFinite(parsed)) return parsed;
  }
  return pageEl.offsetTop;
}

export function scrollToPageElement(
  scrollEl: HTMLElement,
  pageEl: HTMLElement,
  behavior: ScrollBehavior,
): void {
  scrollEl.scrollTo({
    top: Math.max(0, resolvePageScrollTop(pageEl) - 16),
    behavior,
  });
}

export function scrollToPageRegion(
  scrollEl: HTMLElement,
  pageEl: HTMLElement,
  bbox: Bbox | null | undefined,
  renderScale: number,
  behavior: ScrollBehavior,
): boolean {
  const img = pageEl.querySelector("img");
  if (!img || !img.complete || img.naturalWidth <= 0 || img.offsetHeight <= 0) {
    return false;
  }

  if (!isValidBbox(bbox)) {
    scrollToPageElement(scrollEl, pageEl, behavior);
    return true;
  }

  const overlay = bboxToOverlayStyle(bbox, img, renderScale);
  const regionTop = Number.parseFloat(overlay.top);
  const regionHeight = Number.parseFloat(overlay.height);
  const scrollTop =
    resolvePageScrollTop(pageEl) +
    regionTop +
    regionHeight / 2 -
    scrollEl.clientHeight * 0.35;

  scrollEl.scrollTo({ top: Math.max(0, scrollTop), behavior });
  return true;
}
