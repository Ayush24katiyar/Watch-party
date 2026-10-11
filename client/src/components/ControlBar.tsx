import { useEffect, useRef, useState } from "react";
import { Link2, Pause, Play } from "lucide-react";
import type { ClientEvent, PlaybackState } from "../lib/types";
import { parseVideoId } from "../lib/youtube";

const SEEK_DEBOUNCE_MS = 250;

/** Host/moderator transport controls plus the change-video field (D-8). */
export default function ControlBar({
  state,
  isController,
  onAction,
}: {
  state: PlaybackState;
  isController: boolean;
  onAction: (event: ClientEvent) => void;
}) {
  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState("");
  const [seekValue, setSeekValue] = useState(state.currentTime);
  const [scrubbing, setScrubbing] = useState(false);
  const timerRef = useRef<number | null>(null);

  // Follow server time unless the user is dragging the slider.
  useEffect(() => {
    if (!scrubbing) {
      setSeekValue(state.currentTime);
    }
  }, [state.currentTime, scrubbing]);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, []);

  const handleSeek = (value: number) => {
    setSeekValue(value);
    setScrubbing(true);
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
    }
    timerRef.current = window.setTimeout(() => {
      onAction({ type: "seek", payload: { time: value } });
      setScrubbing(false);
    }, SEEK_DEBOUNCE_MS);
  };

  const loadVideo = () => {
    const videoId = parseVideoId(url);
    if (!videoId) {
      setUrlError("That is not a YouTube link. Paste a watch, share, shorts or embed URL.");
      return;
    }
    setUrl("");
    setUrlError("");
    onAction({ type: "change_video", payload: { videoId } });
  };

  if (!isController) {
    return (
      <div className="controls" data-testid="control-bar-readonly">
        <p className="time">
          {state.playState === "playing" ? "Playing" : "Paused"} at{" "}
          {Math.floor(state.currentTime)}s
        </p>
      </div>
    );
  }

  return (
    <div className="controls" data-testid="control-bar">
      <div className="control-row">
        <button
          type="button"
          className="btn btn-primary"
          aria-label={state.playState === "playing" ? "Pause for everyone" : "Play for everyone"}
          onClick={() =>
            onAction({
              type: state.playState === "playing" ? "pause" : "play",
              payload: {},
            })
          }
          data-testid="play-pause"
        >
          {state.playState === "playing" ? <Pause size={16} aria-hidden /> : <Play size={16} aria-hidden />}
          {state.playState === "playing" ? "Pause" : "Play"}
        </button>

        <span className="time">
          {Math.floor(state.currentTime)}s
          <span className="tab-count"> seq {state.seq}</span>
        </span>
      </div>

      <div className="seek">
        <label htmlFor="seek-slider">Seek</label>
        <input
          id="seek-slider"
          type="range"
          min={0}
          max={Math.max(600, Math.floor(seekValue) + 120)}
          value={Math.min(Math.floor(seekValue), 600)}
          onChange={(event) => handleSeek(Number(event.target.value))}
          aria-valuetext={`${Math.floor(seekValue)} seconds`}
        />
        <span className="time">{Math.floor(seekValue)}s</span>
      </div>

      <div className="control-row">
        <label className="sr-only" htmlFor="video-url">
          YouTube link or video ID
        </label>
        <input
          id="video-url"
          className="input url-input"
          value={url}
          placeholder="Paste a YouTube link..."
          onChange={(event) => {
            setUrl(event.target.value);
            if (urlError) {
              setUrlError("");
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              loadVideo();
            }
          }}
          data-testid="video-url-input"
        />
        <button type="button" className="btn" onClick={loadVideo} data-testid="load-video">
          <Link2 size={16} aria-hidden /> Change video
        </button>
      </div>

      {urlError && (
        <p className="error-text" role="alert" data-testid="video-url-error">
          {urlError}
        </p>
      )}
    </div>
  );
}