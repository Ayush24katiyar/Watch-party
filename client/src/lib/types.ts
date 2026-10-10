/** Shared wire-protocol types (camelCase envelope, D-18). */

export type WireEnvelope<TType extends string = string> = {
  type: TType;
  payload: Record<string, unknown>;
  requestId?: string;
};

/** Anonymous identity (D-1): stored in localStorage, sent in headers/join_room. */
export type Identity = {
  userId: string;
  token: string;
};

/** GET /api/rooms/{code} response (8.1). */
export type RoomCheck = {
  code: string;
  joinable: boolean;
  reason?: "not_found" | "full" | "locked" | "closed";
};
