import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Clapperboard, Loader2, LogIn, Plus } from "lucide-react";
import { createRoom, describeError, getRoomCheck } from "../lib/api";
import { clearIdentity, ensureIdentity, loadIdentity } from "../lib/identity";
import type { Identity } from "../lib/types";

const CODE_LENGTH = 6;

/** Landing: create a room, or join with a code. One screen, no marketing. */
export default function LandingPage() {
  const navigate = useNavigate();
  const [identity, setIdentity] = useState<Identity | null>(() => loadIdentity());
  const [username, setUsername] = useState(() => window.localStorage.getItem("watch_party.username") ?? "");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState<"create" | "join" | null>(null);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    if (identity) {
      return;
    }
    ensureIdentity()
      .then(setIdentity)
      .catch(() => setError(describeError(new Error("Could not reach the server."))));
  }, [identity]);

  const name = username.trim() || "guest";

  const handleCreate = async () => {
    if (!identity) {
      return;
    }
    setBusy("create");
    setError("");
    try {
      window.localStorage.setItem("watch_party.username", name);
      const roomCode = await createRoom(identity);
      navigate(`/room/${roomCode}`, { state: { username: name } });
    } catch (err) {
      // A dead token means a fresh identity on the next attempt.
      if (err instanceof Error && err.message.toLowerCase().includes("expired")) {
        clearIdentity();
      }
      setError(describeError(err));
      setBusy(null);
    }
  };

  const handleJoin = async () => {
    if (!identity || checking) {
      return;
    }
    const trimmed = code.trim().toUpperCase();
    if (trimmed.length !== CODE_LENGTH) {
      setError(`A room code is ${CODE_LENGTH} characters.`);
      return;
    }
    setChecking(true);
    setError("");
    try {
      const check = await getRoomCheck(trimmed);
      if (!check.joinable) {
        setError(
          check.reason === "locked"
            ? "That room is locked right now."
            : check.reason === "full"
              ? "That room is full."
              : "No room with that code.",
        );
        return;
      }
      window.localStorage.setItem("watch_party.username", name);
      navigate(`/room/${trimmed}`, { state: { username: name } });
    } catch (err) {
      setError(describeError(err));
    } finally {
      setChecking(false);
    }
  };

  return (
    <main className="landing">
      <div className="landing-inner">
        <span className="brand">
          <Clapperboard size={18} aria-hidden /> Watch party
        </span>
        <h1>Screening room</h1>
        <p className="landing-sub">Start a room or join one with a code.</p>

        <div className="card">
          <label className="field">
            <span>Your name</span>
            <input
              className="input"
              value={username}
              maxLength={24}
              placeholder="guest"
              autoComplete="off"
              onChange={(event) => setUsername(event.target.value)}
              data-testid="username-input"
            />
          </label>
        </div>

        <div className="divider">or</div>

        <div className="card">
          <h2 className="card-title">
            <Plus size={16} aria-hidden /> Start a new room
          </h2>
          <button
            type="button"
            className="btn btn-primary"
            style={{ width: "100%" }}
            disabled={!identity || busy !== null}
            onClick={handleCreate}
            data-testid="create-room"
          >
            {busy === "create" ? <Loader2 size={16} aria-hidden /> : <Plus size={16} aria-hidden />}
            Create room
          </button>
        </div>

        <div className="card">
          <h2 className="card-title">
            <LogIn size={16} aria-hidden /> Join with a code
          </h2>
          <div className="control-row">
            <label className="sr-only" htmlFor="room-code">
              Room code
            </label>
            <input
              id="room-code"
              className="input url-input code-chip"
              value={code}
              maxLength={CODE_LENGTH}
              placeholder="ABC123"
              autoCapitalize="characters"
              autoComplete="off"
              onChange={(event) => setCode(event.target.value.toUpperCase())}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void handleJoin();
                }
              }}
              data-testid="room-code-input"
            />
            <button
              type="button"
              className="btn"
              disabled={!identity || checking}
              onClick={handleJoin}
              data-testid="join-room"
            >
              {checking ? <Loader2 size={16} aria-hidden /> : <LogIn size={16} aria-hidden />}
              Join
            </button>
          </div>
        </div>

        {error && (
          <p className="error-text" role="alert" style={{ marginTop: "var(--sp-4)" }}>
            {error}
          </p>
        )}
      </div>
    </main>
  );
}