import { useEffect, useRef } from "react";
import { AlertTriangle } from "lucide-react";

/** Confirm step for destructive host actions. */
export default function ConfirmDialog({
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    confirmRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onCancel}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="confirm-title">
          <AlertTriangle size={18} aria-hidden /> {title}
        </h2>
        <p style={{ color: "var(--muted)", marginBottom: "var(--sp-4)" }}>{body}</p>
        <div className="control-row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
          <button
            ref={confirmRef}
            type="button"
            className="btn btn-danger"
            onClick={onConfirm}
            data-testid="confirm-action"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}