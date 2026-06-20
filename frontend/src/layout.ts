export const MOBILE_BREAKPOINT = 900;

export function isMobileViewport(width = window.innerWidth): boolean {
  return width <= MOBILE_BREAKPOINT;
}
