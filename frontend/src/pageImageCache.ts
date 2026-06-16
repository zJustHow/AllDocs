const warmed = new Set<string>();

/** Preload a page render URL so revisits and adjacent pages load from cache. */
export function warmPageImage(url: string): void {
  if (warmed.has(url)) return;
  warmed.add(url);
  const img = new Image();
  img.src = url;
}
