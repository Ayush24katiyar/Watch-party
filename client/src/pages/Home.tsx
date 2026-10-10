import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, createRoom, getHealth } from "../lib/api";
import { ensureIdentity } from "../lib/identity";

type BackendStatus = "checking" | "ok" | "down";

/** Home: create a room or join by code (architecture 5.2). */
export default function HomePage() {
  const navigate = useNavigate();
  const [backend, setBackend] = useState<BackendStatus>("checking");
  const [displayName, setDisplayName] = useState("");
  const [joinCode, setJoinCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then(() => setBackend("ok"))
      .catch(() => setBackend("down"));
    return () => controller.abort();
  }, []);

  async function handleCreate() {
    setBusy(true);
    setError(null);
    try {
      // Identity first (D-1), then the room; username is sent with join_room (5.2).
      const identity = await ensureIdentity();
      const code = await createRoom(identity);
      navigate(`/room/${code}`, { state: { username: displayName.trim() } });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function handleJoin(event: React.FormEvent) {
    event.preventDefault();
    const code = joinCode.trim();
    if (code) {
      navigate(`/room/${code.toUpperCase()}`, { state: { username: displayName.trim() } });
    }
  }

  return (
    <main className="home">
      <h1>Watch Party</h1>
      <p data-testid="backend-status">
        {backend === "ok"
          ? "backend OK"
          : backend === "down"
            ? "backend unreachable"
            : 'checking backend...'}
      </p>
      {error && <p className="error">{error}</p>}
      <label>
        Display name (optional here, set on join)
        <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
      </label>
      <div className="actions">
        <button type="button" onClick={handleCreate} disabled={busy}>
          Create room
        </button>
        <form onSubmit={handleJoin} className="join-form">
          <input
            value={joinCode}
            onChange={(e) => setJoinCode(e.target.value)}
            placeholder="ROOM CODE"
            maxLength={16}
          />
          <button type="submit">Join by code</button>
        </form>
      </div>
    </main>
  );
}
