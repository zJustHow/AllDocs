import { useEffect } from "react";
import { useI18n } from "./i18n";

export interface ImageLightboxProps {
  open: boolean;
  src: string;
  alt: string;
  caption?: string;
  onClose: () => void;
}

export default function ImageLightbox({
  open,
  src,
  alt,
  caption,
  onClose,
}: ImageLightboxProps) {
  const { t } = useI18n();

  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="image-lightbox-root" role="presentation">
      <button
        type="button"
        className="image-lightbox-backdrop"
        aria-label={t("viewer.closeEnlarged")}
        onClick={onClose}
      />
      <figure className="image-lightbox-content" role="dialog" aria-modal="true">
        <img src={src} alt={alt} className="image-lightbox-image" />
        {caption ? (
          <figcaption className="image-lightbox-caption">{caption}</figcaption>
        ) : null}
      </figure>
    </div>
  );
}
