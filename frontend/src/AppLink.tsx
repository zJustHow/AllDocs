import type { AnchorHTMLAttributes, MouseEvent } from "react";
import { navigate, type AppPath } from "./routing";

type AppLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: AppPath | string;
};

export function AppLink({ href, onClick, ...rest }: AppLinkProps) {
  return (
    <a
      href={href}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        ) {
          return;
        }
        event.preventDefault();
        navigate(href);
        onClick?.(event);
      }}
      {...rest}
    />
  );
}
