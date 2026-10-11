/**
 * REST client (architecture 8.1). Credentials travel in headers, never URLs (D-5).
 * The token is returned exactly once by POST /api/users (D-1).
 */

import type { Identity, RoomCheck } from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type ApiErrorCode =
  | "unauthorized"
  | "rate_limited"
  | "room_limit"
  | "not_found";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let code: string | null = null;
  let message = `Request failed (${response.status}).`;
  try {
    const body = (await response.json()) as { detail?: { code?: string; message?: string } };
    code = body.detail?.code ?? null;
    message = body.detail?.message ?? message;
  } catch {
    // Non-JSON body; keep the generic message.
  }
  return new ApiError(response.status, code, message);
}

/** Human text for the codes the backend actually emits. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "unauthorized":
        return "Your session expired. Please try again.";
      case "rate_limited":
        return "Too many requests - wait a moment and retry.";
      case "room_limit":
        return "You already have 3 live rooms. Close one first.";
      default:
        return error.message;
    }
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong.";
}

/** Issue an anonymous identity. The token is shown once and stored (D-1). */
export async function createUser(signal?: AbortSignal): Promise<Identity> {
  const response = await fetch(`${API_URL}/api/users`, {
    method: "POST",
    signal,
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return (await response.json()) as Identity;
}

export async function createRoom(
  identity: Identity,
  signal?: AbortSignal,
): Promise<string> {
  const response = await fetch(`${API_URL}/api/rooms`, {
    method: "POST",
    headers: {
      "X-User-Id": identity.userId,
      "X-User-Token": identity.token,
    },
    signal,
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  const body = (await response.json()) as { code: string };
  return body.code;
}

/** Pre-join check (D-3): never open a socket to a room that cannot be joined. */
export async function getRoomCheck(code: string, signal?: AbortSignal): Promise<RoomCheck> {
  const response = await fetch(`${API_URL}/api/rooms/${encodeURIComponent(code)}`, { signal });
  if (!response.ok) {
    throw await parseError(response);
  }
  return (await response.json()) as RoomCheck;
}