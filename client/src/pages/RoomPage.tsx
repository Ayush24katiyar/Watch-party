import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { useRoomSocket } from "../hooks/useRoomSocket";
import { useRoomState } from "../hooks/useRoomState";
import { clearIdentity, ensureIdentity, loadIdentity } from "../lib/identity";
import { CLOSE } from "../lib/protocol";
import type { ClientEvent, Identity, Reaction, RequestActionKind } from "../lib/types";
import ConfirmDialog from "../components/ConfirmDialog";
import ControlBar from "../components/ControlBar";
import type { HostAction } from "../components/ParticipantList";
import PlayerStage from "../components/PlayerStage";
import ReactionsBar from "../components/ReactionsBar";
import RoomSidebar from "../components/RoomSidebar";
import ToastStack, { type Toast, type ToastKind } from "../components/ToastStack";

const WS_URL = import.meta.env.VITE_WS_URL ?? "ws://localhost:8000";
/** Mirrors the server limits (3/s chat, 5/s reactions) so we do not spam errors. */
const CHAT_COOLDOWN_MS = 340;
const REACTION_COOLDOWN_MS = 200;

type PendingConfirm = { action: "remove" | "transfer"; userId: string; username: string };

/** Everything inside a joined room: socket, reducer, and the layout. */
export default function RoomPage() {
  const { code = "" } = useParams<{ code: string }>();
  const location = useLocation();
  const username = (location.state as { username?: string } | null)?.username ?? "";

  const [identity, setIdentity] = useState<Identity | null>(() => loadIdentity());
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const [reaction, setReaction] = useState<{ userId: string; emoji: string } | null>(null);

  const socket = useRoomSocket({
    url: `${WS_URL}/ws/${code.toUpperCase()}`,
    identity,
    username,
    enabled: Boolean(identity),
  });
  const room = useRoomState(socket.lastEvent);
  const { send } = socket;

  const toast = useCallback((message: string, kind: ToastKind = "info") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev.slice(-3), { id, kind, message }]);
    window.setTimeout(() => setToasts((prev) => prev.filter((item) => item.id !== id)), 4000);
  }, []);

  useEffect(() => {
    ensureIdentity()
      .then(setIdentity)
      .catch(() => toast("Could not reach the server.", "error"));
  }, [toast]);

  // A rejected token must be replaced, not retried forever.
  useEffect(() => {
    if (socket.fatal?.code === CLOSE.UNAUTHORIZED || socket.fatal?.code === CLOSE.BAD_JOIN) {
      clearIdentity();
    }
  }, [socket.fatal]);

  // Surface server errors as toasts.
  useEffect(() => {
    const event = socket.lastEvent;
    if (event?.type !== "error") {
      return;
    }
    const kind: ToastKind =
      event.payload.code === "forbidden" || event.payload.code === "invalid_message"
        ? "error"
        : "info";
    toast(event.payload.message, kind);
  }, [socket.lastEvent, toast]);

  // Reactions are not echoed with a username, so pass the id through.
  useEffect(() => {
    const event = socket.lastEvent;
    if (event?.type === "reaction") {
      setReaction({ userId: event.payload.userId, emoji: event.payload.emoji });
    }
  }, [socket.lastEvent]);

  const isController = room.you?.role === "host" || room.you?.role === "moderator";
  const connected = socket.status === "open" && room.you !== null;

  const handleHostAction = (userId: string, action: HostAction) => {
    const target = room.participants.find((participant) => participant.userId === userId);
    const name = target?.username ?? "this person";
    if (action === "promote") {
      send({ type: "assign_role", payload: { userId, role: "moderator" } });
    } else if (action === "demote") {
      send({ type: "assign_role", payload: { userId, role: "participant" } });
    } else if (action === "remove" || action === "transfer") {
      setConfirm({ action, userId, username: name });
    }
  };

  const runConfirmed = () => {
    if (!confirm) {
      return;
    }
    const event: ClientEvent =
      confirm.action === "remove"
        ? { type: "remove_participant", payload: { userId: confirm.userId } }
        : { type: "transfer_host", payload: { userId: confirm.userId } };
    send(event);
    setConfirm(null);
  };

  const lastChatRef = useRef(0);
  const lastReactionRef = useRef(0);

  const handleChat = (text: string) => {
    const now = Date.now();
    if (now - lastChatRef.current < CHAT_COOLDOWN_MS) {
      toast("Slow down - a few messages per second.", "error");
      return;
    }
    lastChatRef.current = now;
    send({ type: "chat", payload: { text } });
  };

  const handleReact = (emoji: Reaction) => {
    const now = Date.now();
    if (now - lastReactionRef.current < REACTION_COOLDOWN_MS) {
      return;
    }
    lastReactionRef.current = now;
    send({ type: "reaction", payload: { emoji } });
  };

  const requestPlayback = (action: RequestActionKind) => {
    send({ type: "request_action", payload: { action, payload: {} } });
  };

  if (socket.fatal) {
    return <TerminalScreen code={socket.fatal.code} message={socket.fatal.reason} />;
  }

  return (
    <main className="room">
      <div className="room-main">
        {socket.status === "reconnecting" && (
          <div className="banner" role="status" data-testid="reconnect-banner">
            <RefreshCw size={16} aria-hidden />
            Reconnecting{socket.retryIn > 0 ? ` in ${socket.retryIn}s` : "..."}
          </div>
        )}

        <PlayerStage
          videoId={room.playback.videoId}
          state={room.playback}
          isController={isController}
          reaction={reaction}
          participants={room.participants}
          onAction={send}
        />

        <ControlBar state={room.playback} isController={isController} onAction={send} />

        {!isController && connected && (
          <div className="control-row">
            <button
              type="button"
              className="btn"
              onClick={() =>
                requestPlayback(room.playback.playState === "playing" ? "pause" : "play")
              }
              data-testid="request-playback"
            >
              Request {room.playback.playState === "playing" ? "pause" : "play"}
            </button>
          </div>
        )}

        <ReactionsBar onReact={handleReact} disabled={!connected} />
      </div>

      <RoomSidebar
        code={code}
        participants={room.participants}
        youId={room.you?.userId ?? null}
        youRole={room.you?.role ?? null}
        locked={room.locked}
        pendingRequests={room.pendingRequests}
        chat={room.chat}
        onHostAction={handleHostAction}
        onLockChange={(locked) => send({ type: "lock_room", payload: { locked } })}
        onResolve={(requestId, approve) => send({ type: "resolve_request", payload: { requestId, approve } })}
        onSendChat={handleChat}
        onCopyCode={() => {
          void navigator.clipboard?.writeText(code.toUpperCase());
          toast("Room code copied.", "success");
        }}
      />

      <ToastStack
        toasts={toasts}
        onDismiss={(id) => setToasts((prev) => prev.filter((item) => item.id !== id))}
      />

      {confirm && (
        <ConfirmDialog
          title={confirm.action === "remove" ? `Remove ${confirm.username}?` : `Make ${confirm.username} host?`}
          body={
            confirm.action === "remove"
              ? "They will be disconnected and cannot rejoin this room."
              : "You will become a moderator and they will control playback."
          }
          confirmLabel={confirm.action === "remove" ? "Remove" : "Transfer"}
          onConfirm={runConfirmed}
          onCancel={() => setConfirm(null)}
        />
      )}
    </main>
  );
}

function TerminalScreen({ code, message }: { code: number; message: string }) {
  const removed = code === CLOSE.REMOVED;
  const replaced = code === CLOSE.REPLACED;
  return (
    <main className="landing">
      <div className="landing-inner" style={{ textAlign: "center" }}>
        <h1>{removed ? "Removed" : replaced ? "Opened elsewhere" : "Disconnected"}</h1>
        <p className="landing-sub">{message}</p>
        <Link to="/" className="btn btn-primary">
          Back to landing
        </Link>
      </div>
    </main>
  );
}