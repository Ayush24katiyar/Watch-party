/** WebSocket wire protocol types and close-code policy (architecture sections 8.0, 8.5). */
import type { WireEnvelope } from "./types";

export const CLOSE_CODES = {
  ROOM_NOT_FOUND: 4001,
  AUTH_FAILED: 4002,
  REMOVED: 4003,
  REPLACED: 4004,
  ROOM_FULL: 4005,
  ROOM_LOCKED: 4006,
  PROTOCOL_ERROR: 4007,
  RATE_LIMITED: 4008,
  TOO_MANY_INVALID: 4009,
  GOING_AWAY: 1001,
  SERVER_RESTART: 1012,
} as const;

/** Client behaviour per close code (8.5). */
export const NO_RETRY_CLOSE_CODES: ReadonlySet<number> = new Set([
  CLOSE_CODES.ROOM_NOT_FOUND,
  CLOSE_CODES.AUTH_FAILED,
  CLOSE_CODES.REMOVED,
  CLOSE_CODES.REPLACED,
  CLOSE_CODES.ROOM_FULL,
  CLOSE_CODES.ROOM_LOCKED,
  CLOSE_CODES.TOO_MANY_INVALID,
]);

/** Protocol errors get exactly one retry (8.5). */
export const RETRY_ONCE_CLOSE_CODES: ReadonlySet<number> = new Set([CLOSE_CODES.PROTOCOL_ERROR]);

export type ServerEvent = WireEnvelope<"ping" | "echo" | "error"> & {
  payload: Record<string, unknown>;
};
