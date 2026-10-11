import { useState } from "react";
import { Link } from "react-router-dom";
import { Copy, LogOut } from "lucide-react";
import ChatPanel from "./ChatPanel";
import ParticipantList, { type HostAction } from "./ParticipantList";
import RequestsQueue from "./RequestsQueue";
import type { ChatMessage, Participant, PendingRequest, Role } from "../lib/types";

type Tab = "people" | "chat" | "requests";

/** Sidebar: People / Chat / Requests tabs, plus the room footer. */
export default function RoomSidebar({
  code,
  participants,
  youId,
  youRole,
  locked,
  pendingRequests,
  chat,
  onHostAction,
  onLockChange,
  onResolve,
  onSendChat,
  onCopyCode,
}: {
  code: string;
  participants: Participant[];
  youId: string | null;
  youRole: Role | null;
  locked: boolean;
  pendingRequests: PendingRequest[];
  chat: ChatMessage[];
  onHostAction: (userId: string, action: HostAction) => void;
  onLockChange: (locked: boolean) => void;
  onResolve: (requestId: string, approve: boolean) => void;
  onSendChat: (text: string) => void;
  onCopyCode: () => void;
}) {
  const [tab, setTab] = useState<Tab>("people");
  const isController = youRole === "host" || youRole === "moderator";
  const openRequests = isController && pendingRequests.length > 0;

  return (
    <aside className="room-aside">
      <div className="card" style={{ display: "flex", flexDirection: "column", minHeight: "28rem" }}>
        <div className="tabs" role="tablist" aria-label="Room">
          <button
            type="button"
            className="tab"
            role="tab"
            aria-selected={tab === "people"}
            onClick={() => setTab("people")}
          >
            People <span className="tab-count">{participants.length}</span>
          </button>
          <button
            type="button"
            className="tab"
            role="tab"
            aria-selected={tab === "chat"}
            onClick={() => setTab("chat")}
          >
            Chat
          </button>
          {openRequests && (
            <button
              type="button"
              className="tab"
              role="tab"
              aria-selected={tab === "requests"}
              onClick={() => setTab("requests")}
            >
              Requests <span className="tab-count">{pendingRequests.length}</span>
            </button>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", flex: 1, paddingTop: "var(--sp-3)" }}>
          {tab === "people" && (
            <ParticipantList
              participants={participants}
              youId={youId}
              youRole={youRole}
              locked={locked}
              onHostAction={onHostAction}
              onLockChange={onLockChange}
            />
          )}
          {tab === "chat" && <ChatPanel messages={chat} youId={youId} onSend={onSendChat} />}
          {tab === "requests" && isController && (
            <RequestsQueue
              requests={pendingRequests}
              isController={isController}
              onResolve={onResolve}
            />
          )}
        </div>

        <div className="room-foot" style={{ paddingTop: "var(--sp-3)" }}>
          <span className="code-chip">{code.toUpperCase()}</span>
          <span className="spacer" />
          <button type="button" className="btn btn-icon" aria-label="Copy room code" onClick={onCopyCode}>
            <Copy size={14} aria-hidden />
          </button>
          <Link to="/" className="btn btn-icon" aria-label="Leave room">
            <LogOut size={14} aria-hidden />
          </Link>
        </div>
      </div>
    </aside>
  );
}