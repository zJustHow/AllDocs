export const MOBILE_BREAKPOINT = 900;
export const PANEL_ANIMATION_MS = 480;
// Keep the closing panel mounted through the animation's final painted frame.
export const PANEL_CLOSE_MS = PANEL_ANIMATION_MS + 40;

export function isMobileViewport(width = window.innerWidth): boolean {
  return width <= MOBILE_BREAKPOINT;
}
