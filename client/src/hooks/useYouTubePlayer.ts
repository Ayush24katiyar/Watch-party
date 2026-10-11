import { useEffect, useRef } from "react";
import { loadYouTubeApi } from "../lib/youtube";
import type { PlaybackState } from "./useRoomState";
import type { PlaybackAction } from "./types";

export type { PlaybackAction } from "./types";

type YtPlayer = NonNullable<Window["YT"]>["Player"] extends new (
  ...args: never[]
) => infer P
  ? P
  : never;

const SYNC_TOLERANCE_SECONDS = 1.5;
// Drift correction is deliberately more forgiving: a real desync is seconds
// (buffer stall, background tab), not the sub-second jitter of normal playback.
const DRIFT_TOLERANCE_SECONDS = 2.5;
const ECHO_GUARD_MS = 500;
const DRIFT_CHECK_MS = 2_000;
// If the embed is still not ready after this, warn (D-8: black/blocked player).
const PLAYER_READY_TIMEOUT_MS = 15_000;

/**
 * YouTube IFrame wrapper (architecture 11, D-8).
 *
 * The IFrame API takes a plain <div> (it creates the <iframe> itself), so the
 * hook owns a container div and rebuilds the embed whenever the video changes
 * (fresh embed per video, D-8). Remote state is applied through a ready-queue
 * and the echo guard (`isApplyingRemote`); a 2 s drift check keeps buffering and
 * background tabs in line (D-21); `ended` is treated as paused at the end.
 */
export function useYouTubePlayer({
  videoId,
  state,
  onAction,
}: {
  videoId: string | null;
  state: PlaybackState;
  onAction: (action: PlaybackAction) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<YtPlayer | null>(null);
  const readyRef = useRef(false);
  const applyingRemoteRef = useRef(false);
  const lastStateRef = useRef<PlaybackState | null>(null);
  const latestVideoIdRef = useRef<string | null>(null);
  const onActionRef = useRef(onAction);
  const readyTimerRef = useRef<number | null>(null);
  /** Wall-clock ms when the current remote state was applied (drift projection). */
  const appliedAtRef = useRef(0);

  useEffect(() => {
    onActionRef.current = onAction;
  }, [onAction]);

  function createPlayer(id?: string) {
    if (!containerRef.current || !window.YT?.Player) {
      console.warn("[WP] yt: cannot create player (api or container missing)");
      return;
    }
    // Fresh embed per video: clear the container first (D-8).
    containerRef.current.innerHTML = "";
    const mount = document.createElement("div");
    containerRef.current.appendChild(mount);
    console.log("[WP] yt player created:", id || "(no video yet)");
    playerRef.current = new window.YT.Player(mount, {
      videoId: id,
      playerVars: { controls: 0, disablekb: 1, rel: 0, modestbranding: 1 },
      events: {
        onReady: () => {
          readyRef.current = true;
          if (readyTimerRef.current !== null) {
            window.clearTimeout(readyTimerRef.current);
            readyTimerRef.current = null;
          }
          console.log("[WP] yt player ready");
          // Player-ready queue (11): apply the latest queued state.
          const queued = lastStateRef.current;
          if (queued) {
            applyRemote(queued);
          }
        },
        onStateChange: (event: { data: number }) => {
          const YT = window.YT;
          if (event.data === YT?.PlayerState.ENDED) {
            console.log("[WP] yt player ended -> pausing at end");
            playerRef.current?.pauseVideo();
          }
          // Echo guard (D-9): the player's own event after applying remote state.
          if (applyingRemoteRef.current) {
            applyingRemoteRef.current = false;
          }
        },
      },
    });
    latestVideoIdRef.current = id ?? null;
    // "Player does not respond" watchdog.
    if (readyTimerRef.current !== null) {
      window.clearTimeout(readyTimerRef.current);
    }
    readyTimerRef.current = window.setTimeout(() => {
      if (!readyRef.current) {
        console.warn(
          "[WP] yt player not responding after",
          PLAYER_READY_TIMEOUT_MS / 1000,
          "s - check the link, network, or YouTube embedding restrictions",
        );
      }
    }, PLAYER_READY_TIMEOUT_MS);
  }

  function destroyPlayer() {
    try {
      playerRef.current?.destroy();
      console.log("[WP] yt player destroyed");
    } catch {
      // already gone
    }
    playerRef.current = null;
    readyRef.current = false;
    latestVideoIdRef.current = null;
    if (containerRef.current) {
      containerRef.current.innerHTML = "";
    }
  }

  function applyRemote(next: PlaybackState) {
    const player = playerRef.current;
    lastStateRef.current = next;
    if (!readyRef.current || !player) {
      return;
    }
    // Anchor the projection clock so the drift check knows where "now" starts.
    appliedAtRef.current = Date.now();
    applyingRemoteRef.current = true;
    const current = player.getCurrentTime();
    if (Math.abs(current - next.currentTime) > SYNC_TOLERANCE_SECONDS) {
      console.log("[WP] applyRemote: seek", current.toFixed(1), "->", next.currentTime.toFixed(1));
      player.seekTo(next.currentTime, true);
    }
    // Skip play/pause when the player is already in that state: calling
    // playVideo() on a playing embed restarts the stream (the "refresh" bug).
    const playerState = player.getPlayerState();
    const isPlaying = playerState === window.YT?.PlayerState?.PLAYING;
    const isPaused = playerState === window.YT?.PlayerState?.PAUSED;
    console.log("[WP] applyRemote:", next.playState, "at", next.currentTime.toFixed(1), "seq", next.seq);
    if (next.playState === "playing" && !isPlaying) {
      player.playVideo();
    } else if (next.playState === "paused" && !isPaused) {
      player.pauseVideo();
    }
    // The player event clears the flag; this is the fallback (D-9).
    window.setTimeout(() => {
      applyingRemoteRef.current = false;
    }, ECHO_GUARD_MS);
  }

  // Video change: (re)build the embed once the API is ready (D-8).
  //
  // There is deliberately no "empty" player: YT.Player with no videoId throws
  // "Invalid video id", which left the container holding a broken embed.
  useEffect(() => {
    if (videoId === latestVideoIdRef.current) {
      return;
    }
    console.log("[WP] yt: video changed ->", videoId ?? "(none)");
    let cancelled = false;
    if (!videoId) {
      destroyPlayer();
      latestVideoIdRef.current = null;
      return () => {
        cancelled = true;
      };
    }
    loadYouTubeApi().then(() => {
      if (cancelled) {
        return;
      }
      destroyPlayer();
      createPlayer(videoId);
    });
    return () => {
      cancelled = true;
    };
  }, [videoId]);

  // Apply incoming server state (seq-guarded by the reducer, D-10).
  useEffect(() => {
    if (lastStateRef.current === state) {
      return;
    }
    if (state.videoId && state.videoId !== latestVideoIdRef.current) {
      // The video effect rebuilds the embed for the new video. Record the state
      // anyway, so onReady applies THIS state and not the previous video's (B-024).
      lastStateRef.current = state;
      return;
    }
    applyRemote(state);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  // Drift check (D-21): every 2 s, correct buffering / background-tab drift.
  //
  // The server's currentTime is a snapshot taken when the event was sent, so it
  // must be projected forward by the elapsed wall time while playing. Comparing
  // against the raw snapshot made the player seek back to the same position on
  // every tick - the visible "play keeps refreshing" loop.
  useEffect(() => {
    const timer = window.setInterval(() => {
      const player = playerRef.current;
      const last = lastStateRef.current;
      if (!readyRef.current || !player || last?.playState !== "playing") {
        return;
      }
      // Never correct while the embed is buffering; it is not drifting, just stalled.
      if (player.getPlayerState() === window.YT?.PlayerState?.BUFFERING) {
        return;
      }
      const elapsed = (Date.now() - appliedAtRef.current) / 1000;
      const expected = last.currentTime + elapsed;
      const actual = player.getCurrentTime();
      if (Math.abs(actual - expected) > DRIFT_TOLERANCE_SECONDS) {
        console.log("[WP] drift correction: seek", actual.toFixed(1), "->", expected.toFixed(1));
        player.seekTo(expected, true);
        // Re-anchor so the next tick measures from the corrected position.
        appliedAtRef.current = Date.now();
        lastStateRef.current = { ...last, currentTime: expected };
      }
    }, DRIFT_CHECK_MS);
    return () => window.clearInterval(timer);
  }, []);

  return { containerRef };
}
