/** Anonymous identity in localStorage (D-1). */

import { createUser } from "./api";
import type { Identity } from "./types";

const USER_ID_KEY = "watch_party.user_id";
const TOKEN_KEY = "watch_party.token";

export function loadIdentity(): Identity | null {
  const userId = window.localStorage.getItem(USER_ID_KEY);
  const token = window.localStorage.getItem(TOKEN_KEY);
  return userId && token ? { userId, token } : null;
}

/**
 * Value equality for identities.
 *
 * loadIdentity() builds a fresh object on every call, so putting its result in
 * state and later replacing it with an equal one is still a new reference.
 * The socket hook keys off that reference, so an equal-but-new identity would
 * tear down a live connection and reconnect - which the server then closes as
 * a duplicate (4004, "opened somewhere else").
 */
export function sameIdentity(a: Identity | null, b: Identity | null): boolean {
  if (a === null || b === null) {
    return a === b;
  }
  return a.userId === b.userId && a.token === b.token;
}

export function saveIdentity(identity: Identity): void {
  window.localStorage.setItem(USER_ID_KEY, identity.userId);
  window.localStorage.setItem(TOKEN_KEY, identity.token);
}

/** Used when auth fails (close 4002): drop identity so the next visit re-registers. */
export function clearIdentity(): void {
  window.localStorage.removeItem(USER_ID_KEY);
  window.localStorage.removeItem(TOKEN_KEY);
}

export async function ensureIdentity(): Promise<Identity> {
  const existing = loadIdentity();
  if (existing) {
    return existing;
  }
  const identity = await createUser();
  saveIdentity(identity);
  return identity;
}

/**
 * Discard a rejected identity and register a new one.
 *
 * Needed because the stored user is dropped from the database (a wiped dev
 * DB, a restored backup). Without this the app keeps retrying credentials the
 * server will never accept, and the user is stuck until they clear storage by
 * hand.
 */
export async function refreshIdentity(): Promise<Identity> {
  clearIdentity();
  const identity = await createUser();
  saveIdentity(identity);
  return identity;
}
