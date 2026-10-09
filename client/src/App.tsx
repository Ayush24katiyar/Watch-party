import { useEffect, useState } from "react";
import { getHealth } from "./lib/api";
import { useWebSocket } from "./hooks/useWebSocket";

type BackendStatus = "checking" | "ok" | "down";

const WS_URL = import.meta.env.VITE_WS_URL ?? "ws://localhost:8000";

/** Phase 1-only debug panel: connect + temporary dev `echo` event. Removed in Phase 2. */
function WebSocketDevPanel() {
  const { status, closeInfo, lastEcho, send } = useWebSocket(`${WS_URL}/ws/dev`);

  useEffect(() => {
    // Phase 1: join_room is schema-validated only; auth/room lookup arrive in Phase 2.
    send({
      type: "join_room",
      payload: { roomId: "dev", username: "dev", userId: "dev", token: "dev" },
    });
  }, [send]);

  const statusText =
    status === "open"
      ? "open"
      : status === "connecting"
        ? "connecting (or reconnecting with backoff)"
        : closeInfo
          ? `closed (code ${closeInfo.code})`
          : "closed";

  return (
    <section className="dev-panel" data-testid="ws-dev-panel">
      <h2>WebSocket dev panel (Phase 1 only)</h2>
      <p>
        status: <strong data-testid="ws-status">{statusText}</strong>
      </p>
      <button
        type="button"
        onClick={() => send({ type: "echo", payload: { hello: "world", sentAt: Date.now() } })}
      >
        send echo
      </button>
      <p data-testid="ws-last-echo">last echo: {lastEcho ? JSON.stringify(lastEcho) : "(none yet)"}</p>
    </section>
  );
}

function App() {
  const [status, setStatus] = useState<BackendStatus>("checking");

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then(() => setStatus("ok"))
      .catch(() => setStatus("down"));
    return () => controller.abort();
  }, []);

  return (
    <main className="home">
      <h1>Watch Party</h1>
      <p data-testid="backend-status">
        {status === "ok"
          ? "backend OK"
          : status === "down"
            ? "backend unreachable"
            : 'checking backend...'}
      </p>
      {import.meta.env.DEV && <WebSocketDevPanel />}
    </main>
  );
}

export default App;
