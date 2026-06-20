import type { ReactNode } from "react";
import { renderHook, type RenderHookOptions } from "@testing-library/react";
import { I18nProvider } from "../i18n";
import type { DocumentItem } from "../types";

export function createI18nWrapper() {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <I18nProvider>{children}</I18nProvider>;
  };
}

export function renderHookWithI18n<Result, Props>(
  hook: (props: Props) => Result,
  options?: Omit<RenderHookOptions<Props>, "wrapper">,
) {
  return renderHook(hook, {
    ...options,
    wrapper: createI18nWrapper(),
  });
}

export const sampleDocument: DocumentItem = {
  id: "doc-1",
  name: "Manual.pdf",
  content_type: "application/pdf",
  status: "ready",
  page_count: 8,
  ocr_pages: null,
  progress: 100,
  progress_message: null,
  error_message: null,
  created_at: "2026-01-01T00:00:00Z",
};

export const processingDocument: DocumentItem = {
  ...sampleDocument,
  id: "doc-2",
  name: "Indexing.pdf",
  status: "processing",
  progress: 40,
};
