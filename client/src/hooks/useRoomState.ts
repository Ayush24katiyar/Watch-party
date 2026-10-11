/**
 * All server state lives here (architecture 8.3). One reducer, one shape.
 *
 * The switch is exhaustive: `never` in the default arm makes a new server
 * event a compile error rather than a silent no-op.
 */

import { useEffect, useReducer } from "react";
import type { ChatMessage, Participant, PendingRequest, PlaybackState, ServerEvent } from "../lib/types";
import { CHAT_MAX } from "../lib/types";

const CHAT_HISTORY = 50;

export type RoomState = {
  you: Participant | null;
  participants: Participant[];
  playback: PlaybackState;
  locked: boolean;
  pendingRequests: PendingRequest[];
  chat: ChatMessage[];
  /** Transient banner text, e.g. "neha is the new host". */
  notice: string | null;
};

export const EMPTY_PLAYBACK: PlaybackState = {
  videoId: null,
  playState: "paused",
  currentTime: 0,
  seq: 0,
};

const INITIAL: RoomState = {
  you: null,
  participants: [],
  playback: EMPTY_PLAYBACK,
  locked: false,
  pendingRequests: [],
  chat: [],
  notice: null,
};

type Action =
  | { kind: "event"; event: ServerEvent }
  | { kind: "clear_notice" }
  | { kind: "optimistic_request"; request: PendingRequest }
  | { kind: "dismiss_request"; requestId: string; outcome: string };

function withRoster(state: RoomState, roster: Participant[]): RoomState {
  return { ...state, participants: roster };
}

function reducer(state: RoomState, action: Action): RoomState {
  if (action.kind === "clear_notice") {
    return state.notice === null ? state : { ...state, notice: null };
  }
  if (action.kind === "optimistic_request") {
    return {
      ...state,
      pendingRequests: [...state.pendingRequests, action.request],
    };
  }
  if (action.kind === "dismiss_request") {
    return {
      ...state,
      notice: action.outcome,
      pendingRequests: state.pendingRequests.filter(
        (request) => request.requestId !== action.requestId,
      ),
    };
  }

  const event = action.event;
  switch (event.type) {
    case "room_joined":
      return {
        ...state,
        you: event.payload.you,
        participants: event.payload.participants,
        playback: event.payload.state,
        locked: event.payload.locked,
        pendingRequests: event.payload.pendingRequests,
        chat: event.payload.recentChat.slice(-CHAT_HISTORY),
        notice: null,
      };

    // Every presence event carries the authoritative roster; replace it whole.
    case "user_joined":
      return withRoster(state, event.payload.participants);
    case "user_left":
      return withRoster(state, event.payload.participants);
    case "role_assigned":
      return withRoster(state, event.payload.participants);
    case "host_transferred": {
      const next = withRoster(state, event.payload.participants);
      const promoted = next.participants.find((p) => p.userId === event.payload.newHostId);
      // Keep the "you" row's own role fresh for the host.
      const you = promoted && promoted.userId === state.you?.userId ? promoted : state.you;
      return {
        ...next,
        you,
        notice: promoted ? `${promoted.username} is now the host.` : state.notice,
      };
    }
    case "participant_removed":
      return withRoster(state, event.payload.participants);

    case "room_locked":
      return { ...state, locked: event.payload.locked };

    case "room_closed":
      return { ...state, notice: "This room has closed." };

    case "sync_state":
      // D-10: ignore anything older than what we already applied.
      if (event.payload.seq <= state.playback.seq) {
        return state;
      }
      return { ...state, playback: event.payload };

    case "request_created": {
      // The requester already added it optimistically.
      const exists = state.pendingRequests.some(
        (request) => request.requestId === event.payload.requestId,
      );
      if (exists) {
        return state;
      }
      return { ...state, pendingRequests: [...state.pendingRequests, event.payload] };
    }

    case "request_resolved": {
      const pending = state.pendingRequests.find(
        (request) => request.requestId === event.payload.requestId,
      );
      return {
        ...withRoster(state, event.payload.participants),
        pendingRequests: state.pendingRequests.filter(
          (request) => request.requestId !== event.payload.requestId,
        ),
        notice:
          pending && pending.userId !== state.you?.userId
            ? `${pending.username}'s request was ${event.payload.approved ? "approved" : "rejected"}.`
            : state.notice,
      };
    }

    case "chat_message":
      return { ...state, chat: [...state.chat, event.payload].slice(-CHAT_HISTORY) };

    case "reaction":
      // Reactions are ephemeral; the player owns the floating layer.
      return state;

    case "error":
      return { ...state, notice: event.payload.message };

    case "ping":
      return state;

    default: {
      const unreachable: never = event;
      return unreachable;
    }
  }
}

export function useRoomState(lastEvent: ServerEvent | null): RoomState {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  useEffect(() => {
    if (lastEvent) {
      dispatch({ kind: "event", event: lastEvent });
    }
  }, [lastEvent]);
  return state;
}

/** Imperative helpers for optimistic UI; kept beside the reducer. */
export function roomActions(dispatch: React.Dispatch<Action>) {
  return {
    clearNotice: () => dispatch({ kind: "clear_notice" }),
    optimisticRequest: (request: PendingRequest) =>
      dispatch({ kind: "optimistic_request", request }),
    dismissRequest: (requestId: string, outcome: string) =>
      dispatch({ kind: "dismiss_request", requestId, outcome }),
  };
}

export type RoomActions = ReturnType<typeof roomActions>;

export { CHAT_MAX };