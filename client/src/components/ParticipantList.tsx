import { useEffect, useState } from "react";
import type { RoomParticipant } from "../hooks/useRoomState";

export type HostAction = "promote" | "demote" | "remove" | "transfer";

/** Participant list with role badges, online dots, and host-only actions (Phase 4). */
export default function ParticipantList({
  participants,
  youId,
  youRole,
  locked,
  onHostAction,
  onLockChange,
}: {
  participants: RoomParticipant[];
  youId: string | null;
  youRole: string | null;
  locked: boolean;
  onHostAction: (userId: string, action: HostAction) => void;
  onLockChange: (locked: boolean) => void;
}) {
  const isHost = youRole === "host";
  // One host action at a time: the server answers with a fresh participant
  // snapshot, and re-clicking in the meantime used to spam the room.
  const [busyUserId, setBusyUserId] = useState<string | null>(null);

  const run = (userId: string, action: HostAction) => {
    setBusyUserId(userId);
    onHostAction(userId, action);
  };

  // The server answers every host action with a fresh snapshot, so release the
  // button as soon as it comes back.
  useEffect(() => {
    setBusyUserId(null);
  }, [participants]);

  return (
    <section className="participants" data-testid="participant-list">
      <div className="participants-header">
        <h2>Participants ({participants.length})</h2>
        {isHost && (
          <button type="button" onClick={() => onLockChange(!locked)} data-testid="lock-toggle">
            {locked ? "Unlock room" : "Lock room"}
          </button>
        )}
      </div>
      {locked && !isHost && <p className="notice">Room is locked to new members.</p>}
      {participants.length === 0 ? (
        <p>Nobody here yet.</p>
      ) : (
        <ul>
          {participants.map((participant) => {
            const isYou = participant.userId === youId;
            const canManage = isHost && !isYou;
            const busy = busyUserId === participant.userId;
            return (
              <li key={participant.userId} data-testid="participant-row">
                <span className={participant.online ? "dot online" : "dot offline"} aria-hidden />
                <span className="name">
                  {participant.username}
                  {isYou ? " (you)" : ""}
                </span>
                <span className={`role role-${participant.role}`}>
                  {participant.role === "host"
                    ? "Host"
                    : participant.role === "moderator"
                      ? "Moderator"
                      : "Participant"}
                </span>
                {canManage && (
                  <span className="host-actions">
                    {participant.role !== "moderator" && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => run(participant.userId, "promote")}
                      >
                        Promote
                      </button>
                    )}
                    {participant.role !== "participant" && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => run(participant.userId, "demote")}
                      >
                        Demote
                      </button>
                    )}
                    {participant.role !== "host" && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => run(participant.userId, "transfer")}
                        data-testid={`transfer-${participant.username}`}
                      >
                        Make host
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => run(participant.userId, "remove")}
                      data-testid={`remove-${participant.username}`}
                    >
                      Remove
                    </button>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
