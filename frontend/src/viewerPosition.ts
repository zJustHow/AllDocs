export type Bbox = [number, number, number, number];

export function isValidBbox(bbox: number[] | null | undefined): bbox is Bbox {
  return Array.isArray(bbox) && bbox.length === 4 && bbox.every(Number.isFinite);
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

  let scrollTop = Math.max(0, pageEl.offsetTop - 16);
  if (isValidBbox(bbox)) {
    const overlay = bboxToOverlayStyle(bbox, img, renderScale);
    const regionTop = Number.parseFloat(overlay.top);
    const regionHeight = Number.parseFloat(overlay.height);
    scrollTop =
      pageEl.offsetTop +
      regionTop +
      regionHeight / 2 -
      scrollEl.clientHeight * 0.35;
  }

  scrollEl.scrollTo({ top: Math.max(0, scrollTop), behavior });
  return true;
}
