import { CircleCheck, CircleX, Info, X } from "lucide-react";

export type ToastKind = "info" | "success" | "error";

export type Toast = {
  id: number;
  kind: ToastKind;
  message: string;
};

const LIFETIME_MS = 4_000;

const ICONS = {
  info: Info,
  success: CircleCheck,
  error: CircleX,
} as const;

/** Transient server messages: forbidden, rate_limited, invalid_message, errors. */
export default function ToastStack({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  return (
    <div className="toasts" role="region" aria-label="Notifications" data-testid="toasts">
      {toasts.map((toast) => {
        const Icon = ICONS[toast.kind];
        return (
          <div
            key={toast.id}
            className={`toast ${toast.kind === "error" ? "toast-error" : toast.kind === "success" ? "toast-success" : ""}`}
            role={toast.kind === "error" ? "alert" : "status"}
          >
            <Icon size={16} aria-hidden />
            <span style={{ flex: 1 }}>{toast.message}</span>
            <button
              type="button"
              className="btn btn-icon"
              aria-label="Dismiss"
              onClick={() => onDismiss(toast.id)}
            >
              <X size={14} aria-hidden />
            </button>
          </div>
        );
      })}
    </div>
  );
}

export { LIFETIME_MS };