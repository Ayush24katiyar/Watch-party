/**
 * Close-code policy (architecture 10.1, 10.2).
 *
 * Decides, per close code, whether to retry, retry once, or stop - and which
 * user-facing outcome to show. Verified against every `close(...)` call site
 * in src/watch_party/ws/endpoint.py.
 */

export const CLOSE = {
  /** You left. */
  LEFT: 1000,
  /** Connection went stale (no pong). */
  STALE: 1001,
  /** Server restarting. */
  RESTARTING: 1012,
  /** Unexpected drop. */
  ABNORMAL: 1006,
  UNAUTHORIZED: 4001,
  BAD_JOIN: 4002,
  REMOVED: 4003,
  REPLACED: 4004,
  FULL: 4005,
  LOCKED: 4006,
  JOIN_TIMEOUT: 4007,
  RATE_LIMITED: 4008,
  TOO_MANY_INVALID: 4009,
} as const;

export type CloseCode = number;

export type CloseAction = "retry" | "retry_once" | "stop";

export type CloseOutcome = {
  action: CloseAction;
  /** Terminal reason the UI shows; null when reconnecting silently. */
  reason: string | null;
  /** Whether the UI must offer a "go to landing" action. */
  fatal: boolean;
};

/** Codes we back off and reconnect on. */
const RETRY_CODES = new Set<number>([CLOSE.STALE, CLOSE.ABNORMAL, CLOSE.RESTARTING]);
/** One quick retry, then give up. */
const RETRY_ONCE_CODES = new Set<number>([CLOSE.JOIN_TIMEOUT]);

const MESSAGES: Record<number, string> = {
  [CLOSE.LEFT]: "You left the room.",
  [CLOSE.UNAUTHORIZED]: "Your session expired. Please rejoin.",
  [CLOSE.BAD_JOIN]: "Could not join this room.",
  [CLOSE.REMOVED]: "You were removed from this room.",
  [CLOSE.REPLACED]: "Room opened in another tab.",
  [CLOSE.FULL]: "This room is full.",
  [CLOSE.LOCKED]: "This room is locked.",
  [CLOSE.RATE_LIMITED]: "Slow down - too many messages.",
  [CLOSE.TOO_MANY_INVALID]: "Too many invalid messages sent.",
};

/**
 * Classify a close. `retryOnceUsed` tracks the one allowed 4007 retry so a
 * second timeout stops instead of looping.
 */
export function classifyClose(code: number, retryOnceUsed: boolean): CloseOutcome {
  if (RETRY_CODES.has(code)) {
    return { action: "retry", reason: null, fatal: false };
  }
  if (RETRY_ONCE_CODES.has(code)) {
    return retryOnceUsed
      ? {
          action: "stop",
          reason: MESSAGES[CLOSE.JOIN_TIMEOUT] ?? "Could not join.",
          fatal: true,
        }
      : { action: "retry_once", reason: null, fatal: false };
  }
  return {
    action: "stop",
    reason: MESSAGES[code] ?? "Connection closed.",
    fatal: true,
  };
}

/** Exponential backoff with jitter: 1s, 2s, 4s ... capped at 15s (16). */
export function backoffDelay(attempt: number, base = 1_000, max = 15_000): number {
  const ceiling = Math.min(max, base * 2 ** attempt);
  return Math.ceil(ceiling / 2 + Math.random() * (ceiling / 2));
}