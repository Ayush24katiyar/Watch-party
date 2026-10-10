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
