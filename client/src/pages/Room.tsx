import { useEffect, useState } from "react";
import { Link, useParams, useLocation } from "react-router-dom";
import { getRoomCheck } from "../lib/api";
import { clearIdentity, ensureIdentity } from "../lib/identity";
import { useWebSocket } from "../hooks/useWebSocket";
import { CLOSE_CODES } from "../lib/protocol";
import type { RoomCheck } from "../lib/types";

const WS_URL = import.meta.env.VITE_WS_URL ?? "ws://localhost:8000";

/** Join screen: pre-check over REST (D-3), then open the socket on click (D-4). */
export default function RoomPage() {
  const { code = "" } = useParams<{ code: string }>();
  const location = useLocation();
  const username = (location.state as { username?: string } | null)?.username ?? "";

  const [check, setCheck] = useState<RoomCheck | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [name, setName] = useState(username);
  const [connecting, setConnecting] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getRoomCheck(code)
      .then((result) => setCheck(result))
      .catch((err: unknown) => setCheckError(err instanceof Error ? err.message : String(err)));
    return () => controller.abort();
  }, [code]);

  if (checkError) {
    return (
      <main className="home">
        <h1>Room {code.toUpperCase()}</h1>
        <p className="error">Could not check the room: {checkError}</p>
        <Link to="/">Back to home</Link>
      </main>
    );
  }
  if (!check) {
    return (
      <main className="home">
        <p>Checking room {code.toUpperCase()}...</p>
      </main>
    );
  }
  if (!check.joinable) {
    const reasons: Record<string, string> = {
      not_found: "This room does not exist (or has closed).",
      full: "This room is full.",
      locked: "This room is locked by the host.",
      closed: "This room has closed.",
    };
    return (
      <main className="home">
        <h1>Room {check.code}</h1>
        <p className="error" data-testid="join-error">
          {reasons[check.reason ?? "not_found"] ?? "This room cannot be joined."}
        </p>
        <Link to="/">Back to home</Link>
      </main>
    );
  }

  return (
    <main className="home">
      <h1>Room {check.code}</h1>
      {connecting ? (
        <JoinPanel code={check.code} username={name} />
      ) : (
        <div className="join-form">
          <label>
            Username
            <input value={name} onChange={(event) => setName(event.target.value)} maxLength={24} />
          </label>
          {/* D-12: the click also unlocks browser autoplay for the player (Phase 5). */}
          <button type="button" onClick={() => setConnecting(true)} data-testid="join-button">
            Join &amp; enable player
          </button>
        </div>
      )}
      <p>
        <Link to="/">Leave</Link>
      </p>
    </main>
  );
}

/** Mounted only after the click (D-4): the WebSocket opens when the user joins. */
function JoinPanel({ code, username }: { code: string; username: string }) {
  const { status, closeInfo, lastEvent, send } = useWebSocket(`${WS_URL}/ws/${code}`);

  useEffect(() => {
    let cancelled = false;
    ensureIdentity()
      .then((identity) => {
        if (cancelled) {
          return;
        }
        // Credentials travel in the first WS message, not the URL (D-5).
        send({
          type: "join_room",
          payload: {
            roomId: code,
            username: username.trim() || "player",
            userId: identity.userId,
            token: identity.token,
          },
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [code, send, username]);

  // Auth failure: drop identity so the next attempt re-registers (8.5, 4002).
  useEffect(() => {
    if (closeInfo?.code === CLOSE_CODES.AUTH_FAILED) {
      clearIdentity();
    }
  }, [closeInfo]);

  const joined =
    lastEvent?.type === "room_joined"
      ? (lastEvent.payload as { you?: { username?: string; role?: string } }).you
      : null;
  const errorEvent =
    lastEvent?.type === "error" ? (lastEvent.payload as { code?: string; message?: string }) : null;

  return (
    <section data-testid="ws-status">
      <p>
        connection: <strong>{status}</strong>
        {closeInfo ? ` (closed ${closeInfo.code})` : ""}
      </p>
      {joined && (
        <p data-testid="joined-as">
          Joined as {joined.username} ({joined.role})
        </p>
      )}
      {errorEvent && <p className="error">{errorEvent.message}</p>}
    </section>
  );
}
