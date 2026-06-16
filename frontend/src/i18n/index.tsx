import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import en from "./locales/en";
import zh from "./locales/zh";

export type Locale = "zh" | "en";

export type TranslationTree = typeof zh;

const LOCALES: Record<Locale, TranslationTree> = { zh, en };
const STORAGE_KEY = "alldocs-locale";

type TranslationValues = Record<string, string | number>;

let activeLocale: Locale = detectInitialLocale();

function detectInitialLocale(): Locale {
  if (typeof window === "undefined") return "zh";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "zh" || stored === "en") return stored;
  const browser = window.navigator.language.toLowerCase();
  return browser.startsWith("zh") ? "zh" : "en";
}

function getNestedValue(tree: TranslationTree, key: string): string | readonly string[] | undefined {
  return key.split(".").reduce<unknown>((node, part) => {
    if (node && typeof node === "object" && part in node) {
      return (node as Record<string, unknown>)[part];
    }
    return undefined;
  }, tree) as string | readonly string[] | undefined;
}

function interpolate(template: string, values?: TranslationValues): string {
  if (!values) return template;
  return template.replace(/\{(\w+)\}/g, (_, token: string) =>
    token in values ? String(values[token]) : `{${token}}`,
  );
}

export function translate(
  locale: Locale,
  key: string,
  values?: TranslationValues,
): string {
  const value = getNestedValue(LOCALES[locale], key);
  if (typeof value !== "string") return key;
  return interpolate(value, values);
}

export function t(key: string, values?: TranslationValues): string {
  return translate(activeLocale, key, values);
}

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, values?: TranslationValues) => string;
  suggestions: readonly string[];
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => detectInitialLocale());

  const setLocale = useCallback((next: Locale) => {
    activeLocale = next;
    setLocaleState(next);
    window.localStorage.setItem(STORAGE_KEY, next);
  }, []);

  useEffect(() => {
    activeLocale = locale;
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.title = translate(locale, "app.title");
  }, [locale]);

  const value = useMemo<I18nContextValue>(
    () => ({
      locale,
      setLocale,
      t: (key, values) => translate(locale, key, values),
      suggestions: LOCALES[locale].suggestions,
    }),
    [locale, setLocale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
