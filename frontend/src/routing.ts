import { useSyncExternalStore } from "react";

export type AppPath = "/" | "/profile" | "/settings" | "/auth/callback";

function subscribe(callback: () => void): () => void {
  window.addEventListener("popstate", callback);
  return () => window.removeEventListener("popstate", callback);
}

function getPath(): AppPath {
  const path = window.location.pathname;
  if (
    path === "/profile" ||
    path === "/settings" ||
    path === "/auth/callback"
  ) {
    return path;
  }
  return "/";
}

export function useAppPath(): AppPath {
  return useSyncExternalStore(subscribe, getPath, getPath);
}

export function navigate(path: AppPath | string): void {
  if (window.location.pathname === path) return;
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
