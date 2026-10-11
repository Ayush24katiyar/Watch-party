/**
 * Wire protocol (architecture 8.0, D-18). camelCase on the wire.
 *
 * Every server event is listed here. `RoomEventType` is the union the reducer
 * switches over exhaustively, so a new server event is a compile error.
 */

export type Role = "host" | "moderator" | "participant";

export type Participant = {
  userId: string;
  username: string;
  role: Role;
  online: boolean;
};

export type PlaybackState = {
  videoId: string | null;
  playState: "playing" | "paused";
  currentTime: number;
  seq: number;
};

export type PendingRequest = {
  requestId: string;
  userId: string;
  username: string;
  action: RequestActionKind;
  payload: Record<string, unknown>;
  /** Epoch seconds (server clock), used for the countdown. */
  expiresAt: number;
};

export type ChatMessage = {
  userId: string;
  username: string;
  text: string;
  createdAt: string;
};

export type RequestActionKind = "play" | "pause" | "seek" | "change_video";

export type RoomCheck = {
  code: string;
  joinable: boolean;
  reason?: "not_found" | "full" | "locked";
};

export type Identity = {
  userId: string;
  token: string;
};

/* ---------------- server -> client ---------------- */

export type ServerEventType =
  | "room_joined"
  | "user_joined"
  | "user_left"
  | "role_assigned"
  | "host_transferred"
  | "participant_removed"
  | "room_locked"
  | "room_closed"
  | "sync_state"
  | "request_created"
  | "request_resolved"
  | "chat_message"
  | "reaction"
  | "ping"
  | "error";

/** Events that carry the authoritative roster; replace it wholesale. */
export const PRESENCE_EVENTS = [
  "user_joined",
  "user_left",
  "role_assigned",
  "host_transferred",
  "participant_removed",
  "request_resolved",
] as const;

/**
 * request_resolved has no `reason` field (verified: handlers/requests.py:136).
 * The expiry variant arrives as its own event from the sweeper with
 * approved:false and no reason, so "expired" is derived from absence.
 */
export type ServerEvent =
  | { type: "room_joined"; payload: RoomJoinedPayload }
  | { type: "user_joined"; payload: { username: string; userId: string; role: Role; participants: Participant[] } }
  | { type: "user_left"; payload: { username: string; userId: string; participants: Participant[] } }
  | { type: "role_assigned"; payload: { userId: string; username: string; role: Role; participants: Participant[] } }
  | { type: "host_transferred"; payload: { oldHostId: string; newHostId: string; participants: Participant[] } }
  | { type: "participant_removed"; payload: { userId: string; participants: Participant[] } }
  | { type: "room_locked"; payload: { locked: boolean } }
  | { type: "room_closed"; payload: { reason: string } }
  | { type: "sync_state"; payload: PlaybackState }
  | { type: "request_created"; payload: PendingRequest }
  | { type: "request_resolved"; payload: { requestId: string; approved: boolean; participants: Participant[] } }
  | { type: "chat_message"; payload: ChatMessage }
  | { type: "reaction"; payload: { userId: string; emoji: string } }
  | { type: "ping"; payload: Record<string, never> }
  | { type: "error"; payload: { code: string; message: string; requestId?: string } };

export type RoomJoinedPayload = {
  you: Participant;
  participants: Participant[];
  state: PlaybackState;
  locked: boolean;
  pendingRequests: PendingRequest[];
  recentChat: ChatMessage[];
};

/* ---------------- client -> server ---------------- */

export type ClientEvent =
  | { type: "join_room"; payload: { roomId: string; username: string; userId: string; token: string } }
  | { type: "leave_room"; payload: { roomId: string } }
  | { type: "play"; payload: { time?: number } }
  | { type: "pause"; payload: { time?: number } }
  | { type: "seek"; payload: { time: number } }
  | { type: "change_video"; payload: { videoId: string } }
  | { type: "assign_role"; payload: { userId: string; role: "moderator" | "participant" } }
  | { type: "remove_participant"; payload: { userId: string } }
  | { type: "transfer_host"; payload: { userId: string } }
  | { type: "lock_room"; payload: { locked: boolean } }
  | { type: "request_action"; payload: { action: RequestActionKind; payload: Record<string, unknown> } }
  | { type: "resolve_request"; payload: { requestId: string; approve: boolean } }
  | { type: "chat"; payload: { text: string } }
  | { type: "reaction"; payload: { emoji: string } }
  | { type: "pong"; payload: Record<string, never> };

/** Reaction allow-list, verbatim from the backend (handlers/chat.py:18). */
export const ALLOWED_EMOJI = ["👍", "❤️", "😂", "😮", "😢", "👏", "🎉", "🔥"] as const;
export type Reaction = (typeof ALLOWED_EMOJI)[number];

export const CHAT_MAX = 500;
export const VIDEO_ID_PATTERN = /^[A-Za-z0-9_-]{11}$/;