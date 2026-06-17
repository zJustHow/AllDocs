import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { documentFileUrl, documentPageRenderUrl } from "./api";
import { formatCitationSnippetExcerpt, type ViewerTarget } from "./citations";
import { getPreviewMode } from "./fileTypes";
import { useI18n } from "./i18n";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  CloseIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from "./icons";
import { warmPageImage } from "./pageImageCache";
import {
  bboxToOverlayStyle,
  isValidBbox,
  scrollToPageElement,
  scrollToPageRegion,
  type Bbox,
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
const DEFAULT_PAGE_ASPECT = 1.414;
const BBOX_LAYOUT_SETTLE_MS = 80;
const BBOX_INITIAL_NAV_MS = 500;
const SCROLL_TO_TARGET_MAX_RETRIES = 48;

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

export default function DocumentViewer({ target, onClose }: DocumentViewerProps) {
  const { t } = useI18n();
  const previewMode = getPreviewMode(target.documentName, target.contentType);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(previewMode === "text");
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(target.page ?? 1);
  const [pageInput, setPageInput] = useState(String(target.page ?? 1));
  const [zoom, setZoom] = useState(100);
  const [renderZoom, setRenderZoom] = useState(100);
  const [pageAspect, setPageAspect] = useState(DEFAULT_PAGE_ASPECT);
  const [loadedPages, setLoadedPages] = useState<Set<number>>(() => new Set());
  const [scrollWidth, setScrollWidth] = useState(0);
  const [highlightStyle, setHighlightStyle] = useState<CSSProperties | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef(new Map<number, HTMLDivElement>());
  const scrollSyncLockRef = useRef(false);
  const currentPageRef = useRef(currentPage);
  const bboxNavStartedAtRef = useRef(0);
  const targetBboxKey = useMemo(
    () => (isValidBbox(target.bbox) ? target.bbox.join(",") : ""),
    [target.bbox],
  );

  const pageCount = target.pageCount ?? null;
  const showPageToolbar = previewMode === "pdf" && pageCount !== null;
  const fileUrl = documentFileUrl(target.documentId);
  const pageNumbers = useMemo(
    () => (pageCount ? Array.from({ length: pageCount }, (_, index) => index + 1) : []),
    [pageCount],
  );

  currentPageRef.current = currentPage;

  useEffect(() => {
    const timer = setTimeout(() => setRenderZoom(zoom), ZOOM_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [zoom]);

  const renderScale = useMemo(
    () => Math.min(4, Math.max(0.5, (renderZoom / 100) * BASE_RENDER_SCALE)),
    [renderZoom],
  );

  const placeholderHeight = useMemo(() => {
    const width = Math.max(scrollWidth - 32, 240) * (zoom / 100);
    return width * pageAspect;
  }, [scrollWidth, zoom, pageAspect]);

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
    (behavior: ScrollBehavior = "auto") => {
      const scrollEl = scrollRef.current;
      if (!scrollEl || pageCount === null) return;

      const page = Math.min(Math.max(1, target.page ?? 1), pageCount);
      ensurePagesLoaded(page);

      const attempt = (retries = 0) => {
        const pageEl = pageRefs.current.get(page);
        if (!pageEl) {
          if (retries < SCROLL_TO_TARGET_MAX_RETRIES) {
            requestAnimationFrame(() => attempt(retries + 1));
          }
          return;
        }

        const regionScrolled = scrollToPageRegion(
          scrollEl,
          pageEl,
          isValidBbox(target.bbox) ? target.bbox : null,
          renderScale,
          behavior,
        );
        if (!regionScrolled) {
          scrollToPageElement(scrollEl, pageEl, behavior);
        }

        scrollSyncLockRef.current = true;
        setCurrentPage(page);
        setPageInput(String(page));
        window.setTimeout(() => {
          scrollSyncLockRef.current = false;
        }, behavior === "smooth" ? 500 : 50);

        if (
          !regionScrolled &&
          isValidBbox(target.bbox) &&
          retries < SCROLL_TO_TARGET_MAX_RETRIES
        ) {
          requestAnimationFrame(() => attempt(retries + 1));
        }
      };

      attempt();
    },
    [ensurePagesLoaded, pageCount, renderScale, target.bbox, target.page],
  );

  const scrollToPage = useCallback(
    (page: number, behavior: ScrollBehavior = "smooth") => {
      const scrollEl = scrollRef.current;
      if (!scrollEl || pageCount === null) return;

      const next = Math.min(Math.max(1, page), pageCount);
      ensurePagesLoaded(next);
      setHighlightStyle(null);

      const scroll = () => {
        const pageEl = pageRefs.current.get(next);
        if (!pageEl) return;
        scrollSyncLockRef.current = true;
        scrollEl.scrollTo({ top: Math.max(0, pageEl.offsetTop - 16), behavior });
        setCurrentPage(next);
        setPageInput(String(next));
        window.setTimeout(() => {
          scrollSyncLockRef.current = false;
        }, behavior === "smooth" ? 500 : 50);
      };

      if (pageRefs.current.get(next)) {
        scroll();
        return;
      }

      requestAnimationFrame(scroll);
    },
    [ensurePagesLoaded, pageCount],
  );

  const updateHighlight = useCallback(() => {
    if (!isValidBbox(target.bbox) || target.page === null) {
      setHighlightStyle(null);
      return;
    }

    const pageEl = pageRefs.current.get(target.page);
    const img = pageEl?.querySelector("img");
    if (!img || !img.complete || img.naturalWidth <= 0 || img.offsetHeight <= 0) {
      setHighlightStyle(null);
      return;
    }

    setHighlightStyle(bboxToOverlayStyle(target.bbox as Bbox, img, renderScale));
  }, [renderScale, target.bbox, target.page]);

  useEffect(() => {
    if (previewMode !== "pdf" || pageCount === null) return;
    const page = Math.min(Math.max(1, target.page ?? 1), pageCount);
    setCurrentPage(page);
    setPageInput(String(page));
    setLoadedPages(new Set(pagesNear(page, pageCount)));
  }, [previewMode, pageCount, target.documentId, target.page]);

  useLayoutEffect(() => {
    if (previewMode !== "pdf" || pageCount === null) return;
    scrollToTarget("auto");
  }, [
    previewMode,
    pageCount,
    scrollToTarget,
    target.documentId,
    target.page,
    targetBboxKey,
  ]);

  useLayoutEffect(() => {
    if (previewMode !== "pdf") return;
    updateHighlight();
  }, [previewMode, updateHighlight, targetBboxKey, target.page, zoom, renderScale]);

  useEffect(() => {
    bboxNavStartedAtRef.current = performance.now();
  }, [target.documentId, target.page, targetBboxKey]);

  useEffect(() => {
    if (previewMode !== "pdf" || !isValidBbox(target.bbox) || target.page === null) {
      return;
    }

    const page = target.page;
    let observer: ResizeObserver | null = null;
    let settleTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const scheduleScroll = () => {
      if (performance.now() - bboxNavStartedAtRef.current > BBOX_INITIAL_NAV_MS) {
        return;
      }
      if (settleTimer) clearTimeout(settleTimer);
      settleTimer = window.setTimeout(() => {
        if (!cancelled) scrollToTarget("auto");
      }, BBOX_LAYOUT_SETTLE_MS);
    };

    const attach = (): boolean => {
      const pageEl = pageRefs.current.get(page);
      const img = pageEl?.querySelector("img");
      if (!img || cancelled) return false;

      const onResize = () => {
        updateHighlight();
        scheduleScroll();
      };

      observer = new ResizeObserver(onResize);
      observer.observe(img);
      onResize();
      return true;
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
      if (settleTimer) clearTimeout(settleTimer);
      observer?.disconnect();
    };
  }, [
    previewMode,
    target.page,
    targetBboxKey,
    updateHighlight,
    scrollToTarget,
    loadedPages,
  ]);

  useEffect(() => {
    const scrollEl = scrollRef.current;
    if (!scrollEl || previewMode !== "pdf") return;

    const updateWidth = () => setScrollWidth(scrollEl.clientWidth);
    updateWidth();

    const observer = new ResizeObserver(updateWidth);
    observer.observe(scrollEl);
    return () => observer.disconnect();
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

    pageRefs.current.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, [ensurePagesLoaded, pageCount, pageNumbers, previewMode]);

  useEffect(() => {
    if (previewMode !== "pdf" || pageCount === null || scrollWidth <= 0) return;
    const timer = window.setTimeout(() => {
      scrollToTarget("auto");
      if (isValidBbox(target.bbox)) {
        updateHighlight();
      }
    }, 60);
    return () => window.clearTimeout(timer);
  }, [
    pageCount,
    previewMode,
    renderScale,
    scrollToTarget,
    scrollWidth,
    target.bbox,
    target.page,
    updateHighlight,
    zoom,
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
    if (scrollSyncLockRef.current || pageCount === null) return;

    const scrollEl = scrollRef.current;
    if (!scrollEl) return;

    const marker = scrollEl.scrollTop + scrollEl.clientHeight * 0.3;
    let bestPage = 1;
    let bestDistance = Number.POSITIVE_INFINITY;

    for (let page = 1; page <= pageCount; page += 1) {
      const element = pageRefs.current.get(page);
      if (!element) continue;
      const pageCenter = element.offsetTop + element.offsetHeight / 2;
      const distance = Math.abs(marker - pageCenter);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestPage = page;
      }
    }

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
    setPageAspect((prev) => (Math.abs(prev - aspect) < 0.01 ? prev : aspect));
  }, []);

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
          {target.section ? <span className="doc-viewer-section">{target.section}</span> : null}
        </div>
        <button className="doc-viewer-close" onClick={onClose} aria-label={t("viewer.close")}>
          <CloseIcon />
        </button>
      </div>

      <div className="doc-viewer-shell">
        <div
          className={`doc-viewer-stage${previewMode === "pdf" ? " doc-viewer-stage--pdf" : ""}`}
        >
          {previewMode === "pdf" ? (
            <div ref={scrollRef} className="doc-viewer-scroll" onScroll={handleScroll}>
              <div className="doc-viewer-canvas doc-viewer-canvas--pdf">
                {error && <p className="doc-viewer-status error-text">{error}</p>}
                {!error &&
                  pageNumbers.map((page) => {
                    const pageUrl = documentPageRenderUrl(
                      target.documentId,
                      page,
                      renderScale,
                    );
                    const isLoaded = loadedPages.has(page);
                    const showHighlight =
                      isLoaded &&
                      target.page === page &&
                      isValidBbox(target.bbox) &&
                      highlightStyle;

                    return (
                      <div
                        key={page}
                        ref={(element) => registerPageRef(page, element)}
                        className="doc-viewer-page"
                        data-page={page}
                        style={
                          isLoaded
                            ? undefined
                            : { minHeight: `${Math.round(placeholderHeight)}px` }
                        }
                      >
                        {isLoaded ? (
                          <div className="doc-viewer-page-media">
                            <img
                              src={pageUrl}
                              alt={`${target.documentName} p.${page}`}
                              className="doc-viewer-image doc-viewer-image--pdf"
                              style={{ width: `${zoom}%` }}
                              draggable={false}
                              loading="lazy"
                              onLoad={(event) => {
                                warmPageImage(pageUrl);
                                handlePageLoad(
                                  event.currentTarget.naturalWidth,
                                  event.currentTarget.naturalHeight,
                                );
                                if (target.page === page) {
                                  updateHighlight();
                                  scrollToTarget("auto");
                                }
                              }}
                              onError={() => setError(t("errors.loadDocumentFailed"))}
                            />
                            {showHighlight ? (
                              <div
                                className="doc-viewer-highlight"
                                style={highlightStyle ?? undefined}
                                aria-hidden="true"
                              />
                            ) : null}
                          </div>
                        ) : (
                          <div
                            className="doc-viewer-page-placeholder"
                            style={{ width: `${zoom}%` }}
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

      {target.snippet && (
        <div className="doc-viewer-snippet">
          <p>{formatCitationSnippetExcerpt(target.snippet)}</p>
        </div>
      )}
    </aside>
  );
}
