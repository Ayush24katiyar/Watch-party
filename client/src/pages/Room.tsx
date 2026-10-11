import { useEffect, useState } from "react";
import { Link, useParams, useLocation } from "react-router-dom";
import { getRoomCheck } from "../lib/api";
import { clearIdentity, ensureIdentity } from "../lib/identity";
import { useWebSocket } from "../hooks/useWebSocket";
import { useRoomState } from "../hooks/useRoomState";
import { CLOSE_CODES } from "../lib/protocol";
import ParticipantList, { type HostAction } from "../components/ParticipantList";
import ControlBar from "../components/ControlBar";
import YouTubePlayer from "../components/YouTubePlayer";
import RequestsPanel from "../components/RequestsPanel";
import ChatPanel from "../components/ChatPanel";
import { parseVideoId } from "../lib/youtube";
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
    <main className="home room-wide">
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
  const { status, closeInfo, lastEvent, send, join } = useWebSocket(`${WS_URL}/ws/${code}`);
  const room = useRoomState(lastEvent);
  const [requesting, setRequesting] = useState(false);

  // Phase 4 host tools (section 9). Every action re-checked on the backend.
  const handleHostAction = (userId: string, action: HostAction) => {
    if (action === "promote") {
      send({ type: "assign_role", payload: { userId, role: "moderator" } });
    } else if (action === "demote") {
      send({ type: "assign_role", payload: { userId, role: "participant" } });
    } else if (action === "remove") {
      send({ type: "remove_participant", payload: { userId } });
    } else if (action === "transfer") {
      send({ type: "transfer_host", payload: { userId } });
    }
  };
  const handleLock = (locked: boolean) => {
    send({ type: "lock_room", payload: { locked } });
  };
  const handleResolve = (requestId: string, approve: boolean) => {
    send({ type: "resolve_request", payload: { requestId, approve } });
  };
  const handleChat = (text: string) => {
    send({ type: "chat", payload: { text } });
  };
  const isApprover = room.you?.role === "host" || room.you?.role === "moderator";

  useEffect(() => {
    let cancelled = false;
    ensureIdentity()
      .then((identity) => {
        if (cancelled) {
          return;
        }
        // Credentials travel in the first WS message, not the URL (D-5).
        // join() also remembers the payload so a reconnect rejoins the room.
        join({
          roomId: code,
          username: username.trim() || "player",
          userId: identity.userId,
          token: identity.token,
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

  const errorEvent =
    lastEvent?.type === "error" ? (lastEvent.payload as { code?: string; message?: string }) : null;
  const joined = room.you !== null;
  const isController = room.you?.role === "host" || room.you?.role === "moderator";

  return (
    <section data-testid="ws-status">
      <p>
        connection: <strong>{status}</strong>
        {closeInfo ? ` (closed ${closeInfo.code})` : ""}
        {joined ? " - joined" : ""}
      </p>
      {errorEvent && <p className="error">{errorEvent.message}</p>}
      {joined && (
        <>
          <p data-testid="joined-as">
            You are {room.you?.username} ({room.you?.role})
          </p>
          <ParticipantList
            participants={room.participants}
            youId={room.you?.userId ?? null}
            youRole={room.you?.role ?? null}
            locked={room.locked}
            onHostAction={handleHostAction}
            onLockChange={handleLock}
          />
          <div className="player-area">
            <YouTubePlayer
              videoId={room.state.videoId}
              state={room.state}
              isController={isController}
              onAction={send}
            />
            <ControlBar
              state={room.state}
              isController={isController}
              onAction={send}
              onRequest={() => setRequesting(true)}
            />
            {isApprover && (
              <RequestsPanel requests={room.pendingRequests} onResolve={handleResolve} />
            )}
          </div>
          <ChatPanel messages={room.chat} youId={room.you?.userId ?? null} onSend={handleChat} />
        </>
      )}
      {requesting && (
        <RequestPicker
          onCancel={() => setRequesting(false)}
          onSubmit={(action, payload) => {
            send({ type: "request_action", payload: { action, payload } });
            setRequesting(false);
          }}
        />
      )}
    </section>
  );
}

/** Phase 6: participant asks for a change; host/moderator approves (8.2). */
function RequestPicker({
  onSubmit,
  onCancel,
}: {
  onSubmit: (action: string, payload: Record<string, unknown>) => void;
  onCancel: () => void;
}) {
  const [action, setAction] = useState("play");
  const [time, setTime] = useState("0");
  const [videoUrl, setVideoUrl] = useState("");
  const [error, setError] = useState("");

  const submit = () => {
    if (action === "seek") {
      const seconds = Number(time);
      if (!Number.isFinite(seconds) || seconds < 0) {
        setError("Enter a valid number of seconds.");
        return;
      }
      onSubmit("seek", { time: seconds });
      return;
    }
    if (action === "change_video") {
      const parsed = parseVideoId(videoUrl);
      if (!parsed) {
        setError("That does not look like a YouTube link. Paste a watch, share, or shorts URL.");
        console.error("[WP] request change_video: could not parse", videoUrl);
        return;
      }
      console.log("[WP] request change_video ->", parsed);
      onSubmit("change_video", { videoId: parsed });
      return;
    }
    onSubmit(action, {});
  };

  return (
    <div className="request-picker" data-testid="request-picker">
      <h3>Request a change</h3>
      <label>
        Action
        <select value={action} onChange={(event) => setAction(event.target.value)}>
          <option value="play">Play</option>
          <option value="pause">Pause</option>
          <option value="seek">Seek</option>
          <option value="change_video">Change video</option>
        </select>
      </label>
      {action === "seek" && (
        <label>
          Time (seconds)
          <input value={time} onChange={(event) => setTime(event.target.value)} />
        </label>
      )}
      {action === "change_video" && (
        <label>
          YouTube link
          <input
            value={videoUrl}
            onChange={(event) => setVideoUrl(event.target.value)}
            placeholder="https://youtube.com/watch?v=..."
          />
        </label>
      )}
      {error && <p className="error">{error}</p>}
      <button type="button" onClick={onCancel}>Cancel</button>
      <button type="button" onClick={submit}>
        Send request
      </button>
    </div>
  );
}
