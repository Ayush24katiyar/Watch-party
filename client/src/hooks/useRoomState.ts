import { useEffect, useReducer } from "react";
import type { WireEnvelope } from "../lib/types";

/** One room member as carried by the wire (8.0/8.3). */
export type RoomParticipant = {
  userId: string;
  username: string;
  role: "host" | "moderator" | "participant";
  online: boolean;
};

/** Server-authoritative playback state (8.0, D-7). */
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
  action: string;
  payload: Record<string, unknown>;
  expiresAt: number;
};

export type ChatMessage = {
  userId: string;
  username: string;
  text: string;
  createdAt: string;
};

export type RoomState = {
  you: RoomParticipant | null;
  participants: RoomParticipant[];
  state: PlaybackState;
  locked: boolean;
  pendingRequests: PendingRequest[];
  chat: ChatMessage[];
};

type RoomJoinedPayload = {
  you: RoomParticipant;
  participants: RoomParticipant[];
  state: PlaybackState;
  locked: boolean;
  recentChat: ChatMessage[];
};

type RoomAction =
  | { type: "room_joined"; payload: RoomJoinedPayload & { pendingRequests: PendingRequest[] } }
  | {
      type: "user_joined" | "user_left" | "role_assigned" | "participant_removed" | "host_transferred";
      payload: { participants: RoomParticipant[] };
    }
  | { type: "room_locked"; payload: { locked: boolean } }
  | { type: "sync_state"; payload: PlaybackState }
  | { type: "request_created"; payload: PendingRequest }
  | {
      type: "request_resolved";
      payload: { requestId: string; approved: boolean; reason?: string };
    }
  | { type: "chat_message"; payload: ChatMessage };

const initialState: RoomState = {
  you: null,
  participants: [],
  state: { videoId: null, playState: "paused", currentTime: 0, seq: 0 },
  locked: false,
  pendingRequests: [],
  chat: [],
};

/** List-changing events carry the full roster; re-derive `you` so role changes,
 * transfers and removals stay reflected (8.3). */
function withParticipants(state: RoomState, participants: RoomParticipant[]): RoomState {
  const you =
    state.you === null
      ? null
      : (participants.find((p) => p.userId === state.you?.userId) ?? state.you);
  return { ...state, participants, you };
}

function reducer(state: RoomState, action: RoomAction): RoomState {
  switch (action.type) {
    case "room_joined":
      return {
        you: action.payload.you,
        participants: action.payload.participants,
        state: action.payload.state,
        locked: action.payload.locked,
        pendingRequests: action.payload.pendingRequests,
        chat: action.payload.recentChat,
      };
    case "user_joined":
    case "user_left":
    case "role_assigned":
    case "participant_removed":
    case "host_transferred":
      return withParticipants(state, action.payload.participants);
    case "room_locked":
      return { ...state, locked: action.payload.locked };
    case "sync_state":
      // D-10: ignore state older than what we already have.
      if (action.payload.seq <= state.state.seq) {
        return state;
      }
      return { ...state, state: action.payload };
    case "request_created":
      // The server sends a flat PendingRequest (8.3), not a nested `request`.
      return {
        ...state,
        pendingRequests: [...state.pendingRequests, action.payload],
      };
    case "request_resolved":
      return {
        ...state,
        pendingRequests: state.pendingRequests.filter(
          (request) => request.requestId !== action.payload.requestId,
        ),
      };
    case "chat_message":
      return { ...state, chat: [...state.chat, action.payload].slice(-50) };
    default:
      return state;
  }
}

/** Fold server events into room state; unknown event types are ignored (Phase 6+). */
export function useRoomState(lastEvent: WireEnvelope | null): RoomState {
  const [state, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    if (lastEvent === null) {
      return;
    }
    dispatch(lastEvent as unknown as RoomAction);
  }, [lastEvent]);

  return state;
}
