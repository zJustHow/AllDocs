import { useCallback, useState } from "react";

export type RightPanelId = "settings" | "viewer";

export function useRightPanels() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [rightPanelOrder, setRightPanelOrder] = useState<RightPanelId[]>([]);

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
    unregisterRightPanel("settings");
  }, [unregisterRightPanel]);

  const toggleSettings = useCallback(() => {
    setSettingsOpen((open) => {
      if (open) {
        unregisterRightPanel("settings");
        return false;
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
