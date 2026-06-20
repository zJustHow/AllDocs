import { useCallback, useEffect, useRef, useState } from "react";
import type { ViewerTarget } from "../citations";
import type { DocumentItem } from "../types";
import { PANEL_CLOSE_MS } from "../layout";
import type { RightPanelId } from "./useRightPanels";

interface UseDocumentViewerOptions {
  documents: DocumentItem[];
  registerRightPanel: (panel: RightPanelId) => void;
  unregisterRightPanel: (panel: RightPanelId) => void;
}

export function useDocumentViewer({
  documents,
  registerRightPanel,
  unregisterRightPanel,
}: UseDocumentViewerOptions) {
  const [viewerTarget, setViewerTarget] = useState<ViewerTarget | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);
  const viewerCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );

  useEffect(
    () => () => {
      if (viewerCloseTimerRef.current)
        clearTimeout(viewerCloseTimerRef.current);
    },
    [],
  );

  const closeViewer = useCallback(
    (immediate = false) => {
      setViewerOpen(false);
      if (viewerCloseTimerRef.current)
        clearTimeout(viewerCloseTimerRef.current);
      const clearTarget = () => {
        setViewerTarget(null);
        unregisterRightPanel("viewer");
        viewerCloseTimerRef.current = null;
      };
      if (immediate) {
        clearTarget();
        return;
      }
      viewerCloseTimerRef.current = setTimeout(clearTarget, PANEL_CLOSE_MS);
    },
    [unregisterRightPanel],
  );

  const openDocument = useCallback(
    (target: ViewerTarget) => {
      const doc = documents.find((d) => d.id === target.documentId);
      if (viewerCloseTimerRef.current) {
        clearTimeout(viewerCloseTimerRef.current);
        viewerCloseTimerRef.current = null;
      }

      const nextTarget = {
        ...target,
        contentType: doc?.content_type ?? target.contentType ?? null,
        pageCount: doc?.page_count ?? target.pageCount ?? null,
      };
      const alreadyOpen = viewerTarget !== null && viewerOpen;

      setViewerTarget(nextTarget);

      if (alreadyOpen) {
        setViewerOpen(true);
        return;
      }

      registerRightPanel("viewer");
      setViewerOpen(true);
    },
    [documents, viewerTarget, viewerOpen, registerRightPanel],
  );

  return {
    viewerTarget,
    viewerOpen,
    openDocument,
    closeViewer,
  };
}
