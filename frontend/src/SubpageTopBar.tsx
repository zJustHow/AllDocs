import type { ReactNode } from "react";
import { ChevronLeftIcon } from "./icons";
import { useI18n } from "./i18n";
import { AppLink } from "./AppLink";

interface SubpageTopBarProps {
  title: string;
  children?: ReactNode;
}

export default function SubpageTopBar({ title, children }: SubpageTopBarProps) {
  const { t } = useI18n();

  return (
    <div className="top-bar-slot">
      <header className="top-bar subpage-top-bar">
        <div className="subpage-top-bar-start">
          <AppLink
            href="/"
            className="icon-btn top-bar-menu subpage-top-bar-back"
            aria-label={t("settings.back")}
          >
            <ChevronLeftIcon />
          </AppLink>
        </div>
        <h1 className="top-bar-title">{title}</h1>
        <div className="subpage-top-bar-end">{children}</div>
      </header>
    </div>
  );
}
