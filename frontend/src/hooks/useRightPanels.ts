import { useCallback, useState } from "react";

export type RightPanelId = "viewer";

export function useRightPanels() {
  const [rightPanelOrder, setRightPanelOrder] = useState<RightPanelId[]>([]);

  const registerRightPanel = useCallback((panel: RightPanelId) => {
    setRightPanelOrder((prev) =>
      prev.includes(panel) ? prev : [...prev, panel],
    );
  }, []);

  const unregisterRightPanel = useCallback((panel: RightPanelId) => {
    setRightPanelOrder((prev) => prev.filter((item) => item !== panel));
  }, []);

  return {
    rightPanelOrder,
    registerRightPanel,
    unregisterRightPanel,
  };
}
