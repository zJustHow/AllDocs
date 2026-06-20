import { useCallback, useEffect, useState } from "react";
import { isMobileViewport, MOBILE_BREAKPOINT } from "../layout";

export function useSidebarLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(() => !isMobileViewport());

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`);
    const onBreakpointChange = (event: MediaQueryListEvent) => {
      if (event.matches) setSidebarOpen(false);
    };
    mq.addEventListener("change", onBreakpointChange);
    return () => mq.removeEventListener("change", onBreakpointChange);
  }, []);

  const toggleSidebar = useCallback(
    () => setSidebarOpen((prev) => !prev),
    [],
  );

  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  const closeSidebarOnMobile = useCallback(() => {
    if (isMobileViewport()) setSidebarOpen(false);
  }, []);

  return {
    sidebarOpen,
    setSidebarOpen,
    toggleSidebar,
    closeSidebar,
    closeSidebarOnMobile,
  };
}
