import type { Identity, RoomCheck } from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type HealthResponse = {
  status: string;
};

/** Low-level fetch wrapper: parses the app's error shape and throws ApiError. */
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
  let message = `request failed with ${response.status}`;
  try {
    const body = (await response.json()) as { detail?: { code?: string; message?: string } };
    code = body.detail?.code ?? null;
    message = body.detail?.message ?? message;
  } catch {
    // keep defaults
  }
  return new ApiError(response.status, code, message);
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_URL}/health`, { signal });
  if (!response.ok) {
    throw await parseError(response);
  }
  return (await response.json()) as HealthResponse;
}

export async function createUser(): Promise<Identity> {
  const response = await fetch(`${API_URL}/api/users`, { method: "POST" });
  if (!response.ok) {
    throw await parseError(response);
  }
  return (await response.json()) as Identity;
}

export async function createRoom(identity: Identity): Promise<string> {
  // Credentials in headers, never in the URL (D-5).
  const response = await fetch(`${API_URL}/api/rooms`, {
    method: "POST",
    headers: { "X-User-Id": identity.userId, "X-User-Token": identity.token },
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  const body = (await response.json()) as { code: string };
  return body.code;
}

export async function getRoomCheck(code: string): Promise<RoomCheck> {
  const response = await fetch(`${API_URL}/api/rooms/${encodeURIComponent(code)}`);
  if (!response.ok) {
    throw await parseError(response);
  }
  return (await response.json()) as RoomCheck;
}
