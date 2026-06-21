import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { documentFileUrl, documentPageRenderUrl, documentPreviewUrl } from "./api";
import { formatCitationSnippetExcerpt, type ViewerTarget } from "./citations";
import { getPreviewMode } from "./fileTypes";
import { useI18n } from "./i18n";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  CloseIcon,
  DocIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from "./icons";
import { warmPageImage } from "./pageImageCache";
import {
  bboxToOverlayStyle,
  highlightRegionsKey,
  isValidBbox,
  resolveHighlightRegions,
  scrollToPageElement,
  scrollToPageRegion,
  type BboxRegion,
} from "./viewerPosition";

interface DocumentViewerProps {
  target: ViewerTarget;
  onClose: () => void;
}

const ZOOM_MIN = 50;
const ZOOM_MAX = 200;
const ZOOM_STEP = 25;
const BASE_RENDER_SCALE = 2;
const ZOOM_DEBOUNCE_MS = 250;
const PAGE_LOAD_BUFFER = 2;
const PAGE_GAP = 12;
const DEFAULT_PAGE_ASPECT = 1.414;
const SCROLL_TO_TARGET_MAX_RETRIES = 48;
const DEFAULT_SCROLL_WIDTH_ESTIMATE = 360;
const RESIZE_SETTLE_MS = 80;

function pagesNear(center: number, pageCount: number): number[] {
  const pages: number[] = [];
  for (
    let page = Math.max(1, center - PAGE_LOAD_BUFFER);
    page <= Math.min(pageCount, center + PAGE_LOAD_BUFFER);
    page += 1
  ) {
    pages.push(page);
  }
  return pages;
}

function pagesForRegions(regions: BboxRegion[], pageCount: number): number[] {
  const pages = new Set<number>();
  for (const region of regions) {
    for (const page of pagesNear(region.page, pageCount)) {
      pages.add(page);
    }
  }
  return [...pages];
}

function pageRowHeight(placeholderHeight: number): number {
  return Math.round(placeholderHeight) + PAGE_GAP;
}

function resolveTargetPage(
  target: ViewerTarget,
  regions: BboxRegion[],
  pageCount: number | null,
): number {
  if (pageCount === null) return target.page ?? 1;
  const primaryPage = regions[0]?.page ?? target.page ?? 1;
  return Math.min(Math.max(1, primaryPage), pageCount);
}

function buildInitialLoadedPages(
  target: ViewerTarget,
  regions: BboxRegion[],
  pageCount: number | null,
): Set<number> {
  if (pageCount === null) return new Set();
  const page = resolveTargetPage(target, regions, pageCount);
  const pages = new Set(pagesNear(page, pageCount));
  for (const regionPage of pagesForRegions(regions, pageCount)) {
    pages.add(regionPage);
  }
  return pages;
}

export default function DocumentViewer({ target, onClose }: DocumentViewerProps) {
  const { t } = useI18n();
  const previewMode = getPreviewMode(target.documentName, target.contentType);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(previewMode === "text");
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(() =>
    resolveTargetPage(target, resolveHighlightRegions(target), target.pageCount ?? null),
  );
  const [pageInput, setPageInput] = useState(() =>
    String(resolveTargetPage(target, resolveHighlightRegions(target), target.pageCount ?? null)),
  );
  const [zoom, setZoom] = useState(100);
  const [renderZoom, setRenderZoom] = useState(100);
  const [pageAspect, setPageAspect] = useState(DEFAULT_PAGE_ASPECT);
  const [loadedPages, setLoadedPages] = useState<Set<number>>(() =>
    buildInitialLoadedPages(
      target,
      resolveHighlightRegions(target),
      target.pageCount ?? null,
    ),
  );
  const [readyPageImages, setReadyPageImages] = useState<Set<number>>(() => new Set());
  const [scrollWidth, setScrollWidth] = useState(0);
  const [resizeMaskVisible, setResizeMaskVisible] = useState(false);
  const [highlightStylesByPage, setHighlightStylesByPage] = useState<
    Map<number, CSSProperties[]>
  >(() => new Map());

  const scrollRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const scrollWidthRef = useRef(0);
  const pageRefs = useRef(new Map<number, HTMLDivElement>());
  const scrollSyncLockRef = useRef(false);
  const resizeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const resizeFrameRef = useRef<number | null>(null);
  const resizingRef = useRef(false);
  const currentPageRef = useRef(currentPage);
  const highlightRegions = useMemo(() => resolveHighlightRegions(target), [target]);
  const primaryRegion = highlightRegions[0] ?? null;
  const targetRegionsKey = useMemo(
    () => highlightRegionsKey(highlightRegions),
    [highlightRegions],
  );

  const pageCount = target.pageCount ?? null;
  const requiredLoadedPages = useMemo(
    () => buildInitialLoadedPages(target, highlightRegions, pageCount),
    [highlightRegions, pageCount, target],
  );
  const effectiveLoadedPages = useMemo(() => {
    const merged = new Set(loadedPages);
    for (const page of requiredLoadedPages) {
      merged.add(page);
    }
    return merged;
  }, [loadedPages, requiredLoadedPages]);

  const showPageToolbar = previewMode === "pdf" && pageCount !== null;
  const fileUrl = documentFileUrl(target.documentId);
  const previewUrl = documentPreviewUrl(target.documentId);
  const fileExtension = target.documentName.split(".").pop()?.toUpperCase() ?? "DOC";
  const resizeMaskLabel =
    previewMode === "image"
      ? fileExtension
      : previewMode === "text"
        ? fileExtension
        : previewMode === "unsupported"
          ? "DOC"
          : previewMode.toUpperCase();

  currentPageRef.current = currentPage;

  useEffect(() => {
    const timer = setTimeout(() => setRenderZoom(zoom), ZOOM_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [zoom]);

  const renderScale = useMemo(
    () => Math.min(4, Math.max(0.5, (renderZoom / 100) * BASE_RENDER_SCALE)),
    [renderZoom],
  );

  const measuredScrollWidth = useMemo(() => {
    if (scrollWidth > 0) return scrollWidth;
    return Math.max(scrollWidthRef.current, DEFAULT_SCROLL_WIDTH_ESTIMATE);
  }, [scrollWidth]);

  const placeholderHeight = useMemo(() => {
    const width = Math.max(measuredScrollWidth - 32, 240) * (zoom / 100);
    return width * pageAspect;
  }, [measuredScrollWidth, zoom, pageAspect]);

  const estimatedPageRowHeight = useMemo(
    () => pageRowHeight(placeholderHeight),
    [placeholderHeight],
  );
  const pageVirtualizer = useVirtualizer({
    count: pageCount ?? 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimatedPageRowHeight,
    overscan: 3,
  });
  const pageVirtualizerRef = useRef(pageVirtualizer);
  pageVirtualizerRef.current = pageVirtualizer;

  useEffect(() => {
    if (previewMode !== "text") {
      setTextContent(null);
      setLoading(false);
      return;
    }

    let active = true;
    setLoading(true);
    setError(null);

    fetch(fileUrl)
      .then(async (response) => {
        if (!response.ok) throw new Error(t("errors.loadDocumentFailed"));
        return response.text();
      })
      .then((text) => {
        if (active) setTextContent(text);
      })
      .catch((err) => {
        if (active) setError(String(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [fileUrl, previewMode, t]);

  const ensurePagesLoaded = useCallback(
    (centerPage: number) => {
      if (pageCount === null) return;
      const nearby = pagesNear(centerPage, pageCount);
      setLoadedPages((prev) => {
        let changed = false;
        const next = new Set(prev);
        for (const page of nearby) {
          if (!next.has(page)) {
            next.add(page);
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    },
    [pageCount],
  );

  const scrollToTarget = useCallback(
    (behavior: ScrollBehavior = "auto"): boolean => {
      const scrollEl = scrollRef.current;
      if (!scrollEl || pageCount === null) return false;

      const page = resolveTargetPage(target, highlightRegions, pageCount);
      ensurePagesLoaded(page);
      scrollSyncLockRef.current = true;
      pageVirtualizerRef.current.scrollToIndex(page - 1, { align: "start", behavior });
      scrollEl.scrollTop = Math.max(
        0,
        (page - 1) * estimatedPageRowHeight - 16,
      );

      const pageEl = pageRefs.current.get(page);
      if (!pageEl) return false;

      const scrollBbox = primaryRegion?.bbox ?? null;
      let positioned = false;
      if (isValidBbox(scrollBbox)) {
        positioned = scrollToPageRegion(
          scrollEl,
          pageEl,
          scrollBbox,
          renderScale,
          behavior,
        );
      }
      if (!positioned) {
        scrollToPageElement(scrollEl, pageEl, behavior);
      }

      setCurrentPage(page);
      setPageInput(String(page));
      return true;
    },
    [
      ensurePagesLoaded,
      estimatedPageRowHeight,
      highlightRegions,
      pageCount,
      primaryRegion,
      renderScale,
      target,
    ],
  );

  const updateHighlights = useCallback(() => {
    if (!highlightRegions.length) {
      setHighlightStylesByPage(new Map());
      return;
    }

    const styles = new Map<number, CSSProperties[]>();
    for (const region of highlightRegions) {
      const pageEl = pageRefs.current.get(region.page);
      const img = pageEl?.querySelector("img");
      if (!img || !img.complete || img.naturalWidth <= 0 || img.offsetHeight <= 0) {
        continue;
      }
      const style = bboxToOverlayStyle(region.bbox, img, renderScale);
      const existing = styles.get(region.page) ?? [];
      existing.push(style);
      styles.set(region.page, existing);
    }
    setHighlightStylesByPage(styles);
  }, [highlightRegions, renderScale]);

  const scrollToPage = useCallback(
    (page: number, behavior: ScrollBehavior = "smooth") => {
      if (pageCount === null) return;

      const next = Math.min(Math.max(1, page), pageCount);
      ensurePagesLoaded(next);
      setHighlightStylesByPage(new Map());
      scrollSyncLockRef.current = true;
      pageVirtualizerRef.current.scrollToIndex(next - 1, { align: "start", behavior });
      setCurrentPage(next);
      setPageInput(String(next));
      window.setTimeout(() => {
        scrollSyncLockRef.current = false;
      }, behavior === "smooth" ? 500 : 50);
    },
    [ensurePagesLoaded, pageCount],
  );

  useEffect(() => {
    setReadyPageImages(new Set());
    setLoadedPages(
      buildInitialLoadedPages(target, resolveHighlightRegions(target), pageCount),
    );
  }, [pageCount, previewMode, target.documentId]);

  useEffect(() => {
    if (previewMode !== "pdf" || pageCount === null) return;
    const page = resolveTargetPage(target, highlightRegions, pageCount);
    setCurrentPage(page);
    setPageInput(String(page));
    setLoadedPages((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const nearbyPage of requiredLoadedPages) {
        if (!next.has(nearbyPage)) {
          next.add(nearbyPage);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [highlightRegions, pageCount, previewMode, requiredLoadedPages, target.documentId, target.page]);

  useLayoutEffect(() => {
    if (previewMode !== "pdf" || pageCount === null) {
      updateHighlights();
      return;
    }

    const finish = () => {
      scrollSyncLockRef.current = false;
      updateHighlights();
    };

    if (scrollToTarget("auto")) {
      finish();
      return;
    }

    let retries = 0;
    const retry = () => {
      if (scrollToTarget("auto") || retries >= SCROLL_TO_TARGET_MAX_RETRIES) {
        finish();
        return;
      }
      retries += 1;
      requestAnimationFrame(retry);
    };
    requestAnimationFrame(retry);
  }, [
    pageCount,
    previewMode,
    scrollToTarget,
    target.documentId,
    target.page,
    targetRegionsKey,
    updateHighlights,
  ]);

  useLayoutEffect(() => {
    if (previewMode !== "pdf") return;
    updateHighlights();
  }, [previewMode, updateHighlights, targetRegionsKey, zoom, renderScale]);

  useEffect(() => {
    if (previewMode !== "pdf" || !highlightRegions.length) {
      return;
    }

    const observedPages = new Set(highlightRegions.map((region) => region.page));
    const observers: ResizeObserver[] = [];
    let cancelled = false;

    const attach = (): boolean => {
      let attached = false;
      for (const page of observedPages) {
        const pageEl = pageRefs.current.get(page);
        const img = pageEl?.querySelector("img");
        if (!img || cancelled) continue;

        const observer = new ResizeObserver(() => {
          updateHighlights();
        });
        observer.observe(img);
        observers.push(observer);
        updateHighlights();
        attached = true;
      }
      return attached;
    };

    if (!attach()) {
      let attempts = 0;
      const retry = () => {
        if (cancelled || attempts >= 24) return;
        attempts += 1;
        if (!attach()) requestAnimationFrame(retry);
      };
      requestAnimationFrame(retry);
    }

    return () => {
      cancelled = true;
      for (const observer of observers) {
        observer.disconnect();
      }
    };
  }, [
    highlightRegions,
    previewMode,
    targetRegionsKey,
    updateHighlights,
    loadedPages,
  ]);

  useLayoutEffect(() => {
    const stageEl = stageRef.current;
    const scrollEl = scrollRef.current;
    if (!stageEl) return;

    const commitWidth = () => {
      if (previewMode !== "pdf" || !scrollEl) return;
      const width = scrollEl.clientWidth;
      if (width <= 0) return;
      scrollWidthRef.current = width;
      setScrollWidth(width);
    };

    commitWidth();
    let observedOuterWidth = stageEl.getBoundingClientRect().width;
    const observer = new ResizeObserver(() => {
      const nextOuterWidth = stageEl.getBoundingClientRect().width;
      if (
        nextOuterWidth <= 0 ||
        Math.abs(nextOuterWidth - observedOuterWidth) < 0.5
      ) {
        return;
      }
      observedOuterWidth = nextOuterWidth;
      resizingRef.current = previewMode === "pdf";
      setResizeMaskVisible(true);
      if (resizeTimerRef.current !== null) {
        clearTimeout(resizeTimerRef.current);
      }
      resizeTimerRef.current = setTimeout(() => {
        resizeTimerRef.current = null;
        commitWidth();
        resizeFrameRef.current = requestAnimationFrame(() => {
          resizeFrameRef.current = null;
          resizingRef.current = false;
          setResizeMaskVisible(false);
        });
      }, RESIZE_SETTLE_MS);
    });
    observer.observe(stageEl);
    return () => {
      observer.disconnect();
      if (resizeTimerRef.current !== null) {
        clearTimeout(resizeTimerRef.current);
        resizeTimerRef.current = null;
      }
      if (resizeFrameRef.current !== null) {
        cancelAnimationFrame(resizeFrameRef.current);
        resizeFrameRef.current = null;
      }
      resizingRef.current = false;
    };
  }, [previewMode]);

  useEffect(() => {
    if (previewMode !== "pdf" || pageCount === null) return;
    const scrollEl = scrollRef.current;
    if (!scrollEl) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const page = Number((entry.target as HTMLElement).dataset.page);
          if (Number.isFinite(page)) ensurePagesLoaded(page);
        }
      },
      { root: scrollEl, rootMargin: "600px 0px", threshold: 0 },
    );

    for (const element of pageRefs.current.values()) {
      observer.observe(element);
    }
    return () => observer.disconnect();
  }, [
    ensurePagesLoaded,
    pageCount,
    previewMode,
    pageVirtualizer.range?.startIndex,
    pageVirtualizer.range?.endIndex,
  ]);

  const goToPage = useCallback(
    (page: number) => {
      scrollToPage(page, "smooth");
    },
    [scrollToPage],
  );

  const commitPage = (raw: string) => {
    const parsed = Number.parseInt(raw, 10);
    if (Number.isNaN(parsed)) {
      setPageInput(String(currentPage));
      return;
    }
    goToPage(parsed);
  };

  const stepPage = useCallback(
    (delta: number) => {
      if (pageCount === null) return;
      scrollToPage(currentPageRef.current + delta, "smooth");
    },
    [pageCount, scrollToPage],
  );

  const adjustZoom = (delta: number) => {
    setZoom((prev) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, prev + delta)));
  };

  const handleScroll = useCallback(() => {
    if (scrollSyncLockRef.current || resizingRef.current || pageCount === null) return;

    const scrollEl = scrollRef.current;
    if (!scrollEl) return;

    // Read the page under the viewport marker from the rendered page positions.
    // Deriving it from an estimated row height drifts when PDF pages have
    // different dimensions or the virtualizer has measured their real sizes.
    const scrollRect = scrollEl.getBoundingClientRect();
    const marker = scrollRect.top + scrollEl.clientHeight * 0.3;
    let bestPage: number | null = null;
    let nearestDistance = Number.POSITIVE_INFINITY;

    for (const [page, pageEl] of pageRefs.current) {
      const rect = pageEl.getBoundingClientRect();
      if (rect.top <= marker && rect.bottom > marker) {
        bestPage = page;
        break;
      }

      const distance = marker < rect.top ? rect.top - marker : marker - rect.bottom;
      if (distance < nearestDistance) {
        nearestDistance = distance;
        bestPage = page;
      }
    }

    if (bestPage === null) return;
    bestPage = Math.min(pageCount, Math.max(1, bestPage));

    ensurePagesLoaded(bestPage);
    setCurrentPage((prev) => {
      if (prev === bestPage) return prev;
      setPageInput(String(bestPage));
      return bestPage;
    });
  }, [ensurePagesLoaded, pageCount]);

  useEffect(() => {
    if (previewMode !== "pdf" || pageCount === null) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        event.preventDefault();
        stepPage(-1);
      } else if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        event.preventDefault();
        stepPage(1);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [previewMode, pageCount, stepPage]);

  const registerPageRef = useCallback((page: number, element: HTMLDivElement | null) => {
    if (element) pageRefs.current.set(page, element);
    else pageRefs.current.delete(page);
  }, []);

  const handlePageLoad = useCallback((width: number, height: number) => {
    if (width <= 0) return;
    const aspect = height / width;
    setPageAspect((prev) => {
      if (Math.abs(prev - aspect) < 0.01) return prev;
      requestAnimationFrame(() => pageVirtualizerRef.current.measure?.());
      return aspect;
    });
  }, []);

  const markPageImageReady = useCallback((page: number) => {
    setReadyPageImages((prev) => {
      if (prev.has(page)) return prev;
      const next = new Set(prev);
      next.add(page);
      return next;
    });
  }, []);

  useLayoutEffect(() => {
    if (previewMode !== "pdf") return;
    for (const page of loadedPages) {
      const img = pageRefs.current.get(page)?.querySelector("img");
      if (img?.complete && img.naturalWidth > 0) {
        markPageImageReady(page);
      }
    }
  }, [loadedPages, markPageImageReady, previewMode, targetRegionsKey]);

  const showToolbar =
    !error &&
    !loading &&
    (previewMode === "pdf"
      ? pageCount !== null
      : previewMode !== "text" || Boolean(textContent));

  return (
    <aside className="doc-viewer">
      <div className="doc-viewer-top">
        <div className="doc-viewer-meta">
          <span className="doc-viewer-name">{target.documentName}</span>
        </div>
        <button type="button" className="icon-btn" onClick={onClose} aria-label={t("viewer.close")}>
          <CloseIcon />
        </button>
      </div>

      <div className="doc-viewer-shell">
        <div
          ref={stageRef}
          className={`doc-viewer-stage${previewMode === "pdf" ? " doc-viewer-stage--pdf" : ""}`}
        >
          {previewMode === "pdf" ? (
            <div ref={scrollRef} className="doc-viewer-scroll" onScroll={handleScroll}>
              <div
                className="doc-viewer-canvas doc-viewer-canvas--pdf"
                style={{ height: `${pageVirtualizer.getTotalSize()}px` }}
              >
                {error && <p className="doc-viewer-status error-text">{error}</p>}
                {!error &&
                  pageVirtualizer.getVirtualItems().map((virtualRow) => {
                    const page = virtualRow.index + 1;
                    const pageUrl = documentPageRenderUrl(
                      target.documentId,
                      page,
                      renderScale,
                    );
                    const isLoaded = effectiveLoadedPages.has(page);
                    const pageHighlights = highlightStylesByPage.get(page) ?? [];
                    const imageReady = readyPageImages.has(page);

                    return (
                      <div
                        key={page}
                        data-index={virtualRow.index}
                        ref={(element) => {
                          pageVirtualizer.measureElement(element);
                          registerPageRef(page, element);
                        }}
                        className="doc-viewer-page"
                        data-page={page}
                        data-page-offset={virtualRow.start}
                        style={{ transform: `translateY(${virtualRow.start}px)` }}
                      >
                        {isLoaded ? (
                          <div
                            className="doc-viewer-page-media"
                            style={{
                              width: `${zoom}%`,
                              height: `${Math.round(placeholderHeight)}px`,
                            }}
                          >
                            <div
                              className="doc-viewer-page-placeholder"
                              aria-hidden="true"
                            />
                            <img
                              src={pageUrl}
                              alt={`${target.documentName} p.${page}`}
                              className={`doc-viewer-image doc-viewer-image--pdf${imageReady ? "" : " doc-viewer-image--pending"}`}
                              style={{ width: "100%" }}
                              draggable={false}
                              loading="eager"
                              onLoad={(event) => {
                                warmPageImage(pageUrl);
                                handlePageLoad(
                                  event.currentTarget.naturalWidth,
                                  event.currentTarget.naturalHeight,
                                );
                                markPageImageReady(page);
                                if (
                                  highlightRegions.some((region) => region.page === page)
                                ) {
                                  updateHighlights();
                                }
                                if (primaryRegion?.page === page) {
                                  requestAnimationFrame(() => scrollToTarget("auto"));
                                }
                              }}
                              onError={() => setError(t("errors.loadDocumentFailed"))}
                            />
                            {pageHighlights.map((style, index) => (
                              <div
                                key={`${page}-${index}`}
                                className="doc-viewer-highlight"
                                style={style}
                                aria-hidden="true"
                              />
                            ))}
                          </div>
                        ) : (
                          <div
                            className="doc-viewer-page-placeholder"
                            style={{
                              width: `${zoom}%`,
                              minHeight: `${Math.round(placeholderHeight)}px`,
                            }}
                            aria-hidden="true"
                          />
                        )}
                      </div>
                    );
                  })}
              </div>
            </div>
          ) : (
            <div
              className="doc-viewer-canvas"
              style={{ transform: `scale(${zoom / 100})` }}
            >
              {loading && previewMode === "text" && (
                <p className="doc-viewer-status">{t("viewer.loading")}</p>
              )}
              {error && <p className="doc-viewer-status error-text">{error}</p>}
              {previewMode === "image" && !error && (
                <img
                  src={fileUrl}
                  alt={target.documentName}
                  className="doc-viewer-image"
                />
              )}
              {previewMode === "text" && textContent && !error && (
                <pre className="doc-viewer-text">{textContent}</pre>
              )}
              {(previewMode === "docx" || previewMode === "html") && !error && (
                <iframe
                  src={previewUrl}
                  title={target.documentName}
                  className="doc-viewer-frame"
                  sandbox=""
                />
              )}
              {previewMode === "unsupported" && !error && (
                <div className="doc-viewer-status">
                  <p>{t("viewer.unsupported")}</p>
                  <a href={fileUrl} download={target.documentName} className="doc-viewer-download">
                    {t("viewer.download")}
                  </a>
                </div>
              )}
            </div>
          )}

          <div
            className={`doc-viewer-resize-mask${resizeMaskVisible ? " is-visible" : ""}`}
            aria-hidden="true"
          >
            <span className={`doc-viewer-resize-file-icon type-${previewMode}`}>
              <DocIcon size={64} />
              <span>{resizeMaskLabel}</span>
            </span>
          </div>

          {showPageToolbar && showToolbar && (
            <div className="doc-viewer-toolbar">
              <button
                type="button"
                className="doc-viewer-toolbar-btn"
                onClick={() => stepPage(-1)}
                disabled={currentPage <= 1}
                aria-label={t("viewer.prevPage")}
              >
                <ChevronLeftIcon />
              </button>
              <span className="doc-viewer-toolbar-label">{t("viewer.pageLabel")}</span>
              <input
                className="doc-viewer-page-input"
                type="text"
                inputMode="numeric"
                value={pageInput}
                onChange={(e) => setPageInput(e.target.value)}
                onBlur={() => commitPage(pageInput)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    commitPage(pageInput);
                    (e.target as HTMLInputElement).blur();
                  }
                }}
                aria-label={t("viewer.page")}
              />
              <span className="doc-viewer-page-total">/ {pageCount ?? "—"}</span>
              <button
                type="button"
                className="doc-viewer-toolbar-btn"
                onClick={() => stepPage(1)}
                disabled={pageCount !== null ? currentPage >= pageCount : false}
                aria-label={t("viewer.nextPage")}
              >
                <ChevronRightIcon />
              </button>
              <span className="doc-viewer-toolbar-divider" aria-hidden="true" />
              <button
                type="button"
                className="doc-viewer-toolbar-btn"
                onClick={() => adjustZoom(-ZOOM_STEP)}
                disabled={zoom <= ZOOM_MIN}
                aria-label={t("viewer.zoomOut")}
              >
                <ZoomOutIcon />
              </button>
              <span className="doc-viewer-zoom-label">{zoom}%</span>
              <button
                type="button"
                className="doc-viewer-toolbar-btn"
                onClick={() => adjustZoom(ZOOM_STEP)}
                disabled={zoom >= ZOOM_MAX}
                aria-label={t("viewer.zoomIn")}
              >
                <ZoomInIcon />
              </button>
            </div>
          )}
        </div>
      </div>

      {(target.section || target.snippet) && (
        <div className="doc-viewer-snippet">
          {target.section ? (
            <p className="doc-viewer-caption" title={target.section}>
              {target.section}
            </p>
          ) : null}
          {target.snippet ? (
            <p>{formatCitationSnippetExcerpt(target.snippet)}</p>
          ) : null}
        </div>
      )}
    </aside>
  );
}
