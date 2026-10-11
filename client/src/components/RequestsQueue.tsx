import { useEffect, useState } from "react";
import { Check, Inbox, X } from "lucide-react";
import type { PendingRequest, RequestActionKind } from "../lib/types";

const DESCRIBE: Record<RequestActionKind, string> = {
  play: "resume playback",
  pause: "pause playback",
  seek: "seek",
  change_video: "change the video",
};

function detail(request: PendingRequest): string {
  if (request.action === "seek") {
    return `to ${String(request.payload.time ?? "?")}s`;
  }
  if (request.action === "change_video") {
    return `to ${String(request.payload.videoId ?? "?")}`;
  }
  return "";
}

/** Pending requests with approve/reject and a live countdown (8.3). */
export default function RequestsQueue({
  requests,
  isController,
  onResolve,
}: {
  requests: PendingRequest[];
  isController: boolean;
  onResolve: (requestId: string, approve: boolean) => void;
}) {
  const [, tick] = useState(0);

  // One timer for the whole list, not one per row.
  useEffect(() => {
    if (requests.length === 0) {
      return;
    }
    const timer = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, [requests.length]);

  if (requests.length === 0) {
    return (
      <p className="empty-state">
        <Inbox size={20} aria-hidden /> No pending requests.
      </p>
    );
  }

  return (
    <div data-testid="requests-queue">
      {requests.map((request) => {
        const left = Math.max(0, Math.ceil(request.expiresAt - Date.now() / 1000));
        return (
          <div className="request" key={request.requestId} data-testid="request-row">
            <div className="request-head">
              <strong>{request.username}</strong>
              <span>
                wants to {DESCRIBE[request.action]} {detail(request)}
              </span>
              <span className="request-count" title="Seconds before this expires">
                {left}s
              </span>
            </div>
            {isController && (
              <div className="control-row">
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  onClick={() => onResolve(request.requestId, true)}
                  data-testid="approve-request"
                >
                  <Check size={14} aria-hidden /> Approve
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => onResolve(request.requestId, false)}
                >
                  <X size={14} aria-hidden /> Reject
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}