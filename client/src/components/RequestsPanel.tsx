import type { PendingRequest } from "../hooks/useRoomState";

/** Phase 6: approver view - approve or reject participant requests (8.3). */
export default function RequestsPanel({
  requests,
  onResolve,
}: {
  requests: PendingRequest[];
  onResolve: (requestId: string, approve: boolean) => void;
}) {
  if (requests.length === 0) {
    return null;
  }
  return (
    <section className="requests-panel" data-testid="requests-panel">
      <h2>Pending requests</h2>
      <ul>
        {requests.map((request) => (
          <li key={request.requestId} data-testid="request-row">
            <span>
              {request.username} wants to {request.action}
              {request.action === "seek" && ` to ${String(request.payload.time)}s`}
              {request.action === "change_video" && ` (${String(request.payload.videoId)})`}
            </span>
            <button type="button" onClick={() => onResolve(request.requestId, true)}>
              Approve
            </button>
            <button type="button" onClick={() => onResolve(request.requestId, false)}>
              Reject
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
