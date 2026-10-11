import { useEffect, useRef, useState } from "react";
import type { PlaybackState } from "../hooks/useRoomState";
import type { PlaybackAction } from "../hooks/useYouTubePlayer";
import { parseVideoId } from "../lib/youtube";

// Dragging the seek slider must not broadcast one seek per pixel.
const SEEK_DEBOUNCE_MS = 250;

/** Custom control bar (D-8): replaces YouTube's native controls. */
export default function ControlBar({
  state,
  isController,
  onAction,
  onRequest,
}: {
  state: PlaybackState;
  isController: boolean;
  onAction: (action: PlaybackAction) => void;
  onRequest: () => void;
}) {
  if (!isController) {
    // Participants: overlay blocks clicks; they may request changes instead (Phase 6).
    return (
      <div className="control-bar disabled" data-testid="control-bar-disabled">
        <p>
          {state.playState === "playing" ? "Playing" : "Paused"} at{" "}
          {Math.floor(state.currentTime)}s — only the host/moderator controls playback.
        </p>
        <button type="button" onClick={onRequest} data-testid="request-button">
          Request a change
        </button>
      </div>
    );
  }

  return <ControllerControls state={state} onAction={onAction} />;
}

function ControllerControls({
  state,
  onAction,
}: {
  state: PlaybackState;
  onAction: (action: PlaybackAction) => void;
}) {
  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState("");
  const [seekValue, setSeekValue] = useState(state.currentTime);
  const [seekPending, setSeekPending] = useState(false);
  const seekTimer = useRef<number | null>(null);

  // Track the server position unless the user is mid-drag.
  useEffect(() => {
    if (!seekPending) {
      setSeekValue(state.currentTime);
    }
  }, [state.currentTime, seekPending]);

  useEffect(() => {
    return () => {
      if (seekTimer.current !== null) {
        window.clearTimeout(seekTimer.current);
      }
    };
  }, []);

  const handleSeek = (value: number) => {
    setSeekValue(value);
    setSeekPending(true);
    if (seekTimer.current !== null) {
      window.clearTimeout(seekTimer.current);
    }
    seekTimer.current = window.setTimeout(() => {
      onAction({ type: "seek", payload: { time: value } });
      setSeekPending(false);
    }, SEEK_DEBOUNCE_MS);
  };

  const loadVideo = () => {
    const videoId = parseVideoId(url);
    if (!videoId) {
      setUrlError("That does not look like a YouTube link. Paste a watch, share, or shorts URL.");
      console.error("[WP] change_video: could not parse", url);
      return;
    }
    setUrlError("");
    setUrl("");
    console.log("[WP] change_video ->", videoId);
    onAction({ type: "change_video", payload: { videoId } });
  };

  return (
    <div className="control-bar" data-testid="control-bar">
      <div className="control-row">
        <button
          type="button"
          onClick={() =>
            onAction({ type: state.playState === "playing" ? "pause" : "play", payload: {} })
          }
        >
          {state.playState === "playing" ? "Pause" : "Play"}
        </button>
        <span className="time">
          {Math.floor(state.currentTime)}s / seq {state.seq}
        </span>
      </div>

      <label className="seek-label">
        Seek to
        <input
          type="range"
          min={0}
          max={Math.max(600, Math.floor(seekValue) + 120)}
          value={Math.min(Math.floor(seekValue), 600)}
          onChange={(event) => handleSeek(Number(event.target.value))}
        />
      </label>

      <div className="control-row change-video">
        <input
          value={url}
          onChange={(event) => {
            setUrl(event.target.value);
            if (urlError) {
              setUrlError("");
            }
          }}
          placeholder="Paste a YouTube link..."
          aria-label="Video URL"
          data-testid="video-url-input"
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              loadVideo();
            }
          }}
        />
        <button type="button" onClick={loadVideo} data-testid="load-video">
          Change video
        </button>
      </div>
      {urlError && (
        <p className="error" data-testid="video-url-error">
          {urlError}
        </p>
      )}
    </div>
  );
}