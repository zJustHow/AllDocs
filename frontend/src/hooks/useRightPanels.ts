import { useCallback, useEffect, useRef, useState } from "react";
import { PANEL_CLOSE_MS } from "../layout";

export type RightPanelId = "settings" | "viewer";

export function useRightPanels() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [rightPanelOrder, setRightPanelOrder] = useState<RightPanelId[]>([]);
  const settingsCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );

  useEffect(
    () => () => {
      if (settingsCloseTimerRef.current)
        clearTimeout(settingsCloseTimerRef.current);
    },
    [],
  );

  const registerRightPanel = useCallback((panel: RightPanelId) => {
    setRightPanelOrder((prev) =>
      prev.includes(panel) ? prev : [...prev, panel],
    );
  }, []);

  const unregisterRightPanel = useCallback((panel: RightPanelId) => {
    setRightPanelOrder((prev) => prev.filter((item) => item !== panel));
  }, []);

  const closeSettings = useCallback(() => {
    setSettingsOpen(false);
    if (settingsCloseTimerRef.current)
      clearTimeout(settingsCloseTimerRef.current);
    settingsCloseTimerRef.current = setTimeout(() => {
      unregisterRightPanel("settings");
      settingsCloseTimerRef.current = null;
    }, PANEL_CLOSE_MS);
  }, [unregisterRightPanel]);

  const toggleSettings = useCallback(() => {
    setSettingsOpen((open) => {
      if (open) {
        if (settingsCloseTimerRef.current)
          clearTimeout(settingsCloseTimerRef.current);
        settingsCloseTimerRef.current = setTimeout(() => {
          unregisterRightPanel("settings");
          settingsCloseTimerRef.current = null;
        }, PANEL_CLOSE_MS);
        return false;
      }
      if (settingsCloseTimerRef.current) {
        clearTimeout(settingsCloseTimerRef.current);
        settingsCloseTimerRef.current = null;
      }
      registerRightPanel("settings");
      return true;
    });
  }, [registerRightPanel, unregisterRightPanel]);

  return {
    settingsOpen,
    rightPanelOrder,
    registerRightPanel,
    unregisterRightPanel,
    closeSettings,
    toggleSettings,
  };
}
