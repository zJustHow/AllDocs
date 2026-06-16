import { useEffect, useRef } from "react";
import { useI18n } from "./i18n";

export interface ConfirmDialogProps {
  open: boolean;
  message: string;
  title?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "default" | "danger";
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  message,
  title,
  confirmLabel,
  cancelLabel,
  variant = "default",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const { t } = useI18n();
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;

    cancelRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="confirm-dialog-root" role="presentation">
      <button
        type="button"
        className="confirm-dialog-backdrop"
        aria-label={t("dialog.close")}
        onClick={onCancel}
      />
      <div
        className="confirm-dialog glass-strong"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={title ? "confirm-dialog-title" : undefined}
        aria-describedby="confirm-dialog-message"
      >
        {title ? (
          <h2 id="confirm-dialog-title" className="confirm-dialog-title">
            {title}
          </h2>
        ) : null}
        <p id="confirm-dialog-message" className="confirm-dialog-message">
          {message}
        </p>
        <div className="confirm-dialog-actions">
          <button
            ref={cancelRef}
            type="button"
            className="confirm-dialog-btn"
            onClick={onCancel}
          >
            {cancelLabel ?? t("dialog.cancel")}
          </button>
          <button
            type="button"
            className={`confirm-dialog-btn primary ${variant === "danger" ? "danger" : ""}`}
            onClick={onConfirm}
          >
            {confirmLabel ?? t("dialog.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
