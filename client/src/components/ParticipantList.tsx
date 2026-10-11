import { Crown, MoreHorizontal, Shield, ShieldOff, Trash2, UserMinus } from "lucide-react";
import { useState } from "react";
import RoleBadge from "./RoleBadge";
import type { Participant, Role } from "../lib/types";

export type HostAction = "promote" | "demote" | "remove" | "transfer";

/** Roster with presence, role badges, and host-only tools (section 9). */
export default function ParticipantList({
  participants,
  youId,
  youRole,
  locked,
  onHostAction,
  onLockChange,
}: {
  participants: Participant[];
  youId: string | null;
  youRole: Role | null;
  locked: boolean;
  onHostAction: (userId: string, action: HostAction) => void;
  onLockChange: (locked: boolean) => void;
}) {
  const isHost = youRole === "host";
  // One host action at a time; the server answers with a fresh roster.
  const [busyId, setBusyId] = useState<string | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);

  const run = (userId: string, action: HostAction) => {
    setBusyId(userId);
    setMenuFor(null);
    onHostAction(userId, action);
  };

  return (
    <div>
      <div className="control-row" style={{ justifyContent: "space-between", marginBottom: "var(--sp-2)" }}>
        <h2>
          Participants <span className="tab-count">({participants.length})</span>
        </h2>
        {isHost && (
          <button
            type="button"
            className="btn btn-sm"
            aria-pressed={locked}
            onClick={() => onLockChange(!locked)}
          >
            {locked ? "Unlock" : "Lock"}
          </button>
        )}
      </div>

      <ul className="roster" data-testid="participant-list">
        {participants.map((participant) => {
          const isYou = participant.userId === youId;
          const busy = busyId === participant.userId;
          const menuOpen = menuFor === participant.userId;
          return (
            <li key={participant.userId} data-testid="participant-row">
              <span
                className={participant.online ? "dot dot-online" : "dot"}
                aria-label={participant.online ? "online" : "offline"}
              />
              <span className="name">
                {participant.username}
                {isYou && <span className="you"> (you)</span>}
              </span>
              <RoleBadge role={participant.role} />

              {isHost && !isYou && (
                <span className="row-actions">
                  <button
                    type="button"
                    className="btn btn-icon"
                    aria-label={`Actions for ${participant.username}`}
                    aria-expanded={menuOpen}
                    disabled={busy}
                    onClick={() => setMenuFor(menuOpen ? null : participant.userId)}
                  >
                    <MoreHorizontal size={16} aria-hidden />
                  </button>
                </span>
              )}

              {isHost && !isYou && menuOpen && (
                <span className="row-actions" data-testid={`actions-${participant.username}`}>
                  {participant.role === "participant" && (
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => run(participant.userId, "promote")}
                    >
                      <Shield size={14} aria-hidden /> Mod
                    </button>
                  )}
                  {participant.role === "moderator" && (
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => run(participant.userId, "demote")}
                    >
                      <ShieldOff size={14} aria-hidden /> Demote
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => run(participant.userId, "transfer")}
                  >
                    <Crown size={14} aria-hidden /> Host
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-danger"
                    data-testid={`remove-${participant.username}`}
                    onClick={() => run(participant.userId, "remove")}
                  >
                    <Trash2 size={14} aria-hidden />
                    <span className="sr-only">Remove {participant.username}</span>
                  </button>
                </span>
              )}
            </li>
          );
        })}
      </ul>

      {participants.length === 0 && (
        <p className="empty-state">
          <UserMinus size={20} aria-hidden /> Nobody here yet.
        </p>
      )}
    </div>
  );
}