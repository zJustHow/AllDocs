import { useLayoutEffect, type RefObject } from "react";

/** Keep --composer-stack-height in sync with the floating composer block. */
export function useComposerStackHeight(
  composerRef: RefObject<HTMLElement | null>,
  syncKey: unknown,
) {
  useLayoutEffect(() => {
    const composer = composerRef.current;
    const shell = composer?.closest(".chat-shell") as HTMLElement | null;
    if (!composer || !shell) return;

    const sync = () => {
      shell.style.setProperty(
        "--composer-stack-height",
        `${composer.getBoundingClientRect().height}px`,
      );
    };

    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(composer);
    window.addEventListener("resize", sync);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", sync);
    };
  }, [composerRef, syncKey]);
}

export function readComposerStackHeight(
  container?: HTMLElement | null,
): number {
  if (typeof getComputedStyle !== "function") return 100;
  const shell =
    container?.closest(".chat-shell") ??
    document.querySelector<HTMLElement>(".chat-shell");
  if (!shell) return 100;
  const parsed = parseFloat(
    getComputedStyle(shell).getPropertyValue("--composer-stack-height"),
  );
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 100;
}
