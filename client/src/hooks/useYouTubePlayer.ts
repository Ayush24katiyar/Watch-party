/**
 * YouTube IFrame sync (architecture 11, D-7..D-9, D-21).
 *
 * The server is the source of truth. `sync_state` carries a seq; older ones
 * are ignored. `currentTime` is a snapshot taken when the event was sent, so
 * the drift check projects it forward by elapsed wall time - comparing against
 * the raw snapshot makes the player rewind every tick.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { ClientEvent, PlaybackState } from "../lib/types";
import { loadYouTubeApi } from "../lib/youtube";

const SYNC_TOLERANCE = 1.5; // seconds of real drift before we seek (spec: ~1s)
const DRIFT_TOLERANCE = 2.5; // looser: jitter is not drift
const DRIFT_CHECK_MS = 2_000;
const READY_TIMEOUT_MS = 15_000;

type PlayerInstance = {
  playVideo: () => void;
  pauseVideo: () => void;
  seekTo: (seconds: number, allowSeekAhead: boolean) => void;
  getCurrentTime: () => number;
  getPlayerState: () => number;
  destroy: () => void;
};

export type PlayerStatus = "idle" | "loading" | "ready" | "error";

export function useYouTubePlayer({
  videoId,
  state,
  send,
  isController,
}: {
  videoId: string | null;
  state: PlaybackState;
  send: (event: ClientEvent) => void;
  isController: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<PlayerInstance | null>(null);
  const readyRef = useRef(false);
  const mountedVideoRef = useRef<string | null>(null);
  const lastStateRef = useRef<PlaybackState | null>(null);
  const appliedAtRef = useRef(0);
  // Suppress our own player events from becoming new commands (echo guard).
  const applyingRemoteRef = useRef(false);
  const sendRef = useRef(send);
  const isControllerRef = useRef(isController);
  sendRef.current = send;
  isControllerRef.current = isController;

  const [status, setStatus] = useState<PlayerStatus>("idle");

  const applyRemote = useCallback((next: PlaybackState) => {
    lastStateRef.current = next;
    const player = playerRef.current;
    if (!readyRef.current || !player) {
      return;
    }
    appliedAtRef.current = Date.now();
    applyingRemoteRef.current = true;
    const current = player.getCurrentTime();
    if (Math.abs(current - next.currentTime) > SYNC_TOLERANCE) {
      player.seekTo(next.currentTime, true);
    }
    const state = player.getPlayerState();
    const isPlaying = state === window.YT?.PlayerState?.PLAYING;
    const isPaused = state === window.YT?.PlayerState?.PAUSED;
    // Only act when the embed is not already there, or it restarts the stream.
    if (next.playState === "playing" && !isPlaying) {
      player.playVideo();
    } else if (next.playState === "paused" && !isPaused) {
      player.pauseVideo();
    }
    window.setTimeout(() => {
      applyingRemoteRef.current = false;
    }, 500);
  }, []);

  // Build a fresh embed when the video changes (D-8). No player without a video:
  // YT.Player with no videoId throws and leaves a broken frame.
  useEffect(() => {
    if (videoId === mountedVideoRef.current) {
      return;
    }
    let cancelled = false;

    const destroy = () => {
      try {
        playerRef.current?.destroy();
      } catch {
        // Already gone.
      }
      playerRef.current = null;
      readyRef.current = false;
      mountedVideoRef.current = null;
      if (containerRef.current) {
        containerRef.current.innerHTML = "";
      }
    };

    if (!videoId) {
      destroy();
      setStatus("idle");
      return () => {
        cancelled = true;
      };
    }

    setStatus("loading");
    loadYouTubeApi()
      .then(() => {
        if (cancelled || !containerRef.current) {
          return;
        }
        destroy();
        const mount = document.createElement("div");
        containerRef.current.appendChild(mount);

        playerRef.current = new window.YT!.Player(mount, {
          videoId,
          playerVars: {
            controls: 0,
            disablekb: 1,
            rel: 0,
            modestbranding: 1,
            playsinline: 1,
          },
          events: {
            onReady: () => {
              if (cancelled) {
                return;
              }
              readyRef.current = true;
              setStatus("ready");
              // Apply whatever state arrived while the embed was loading.
              if (lastStateRef.current) {
                applyRemote(lastStateRef.current);
              }
            },
            onStateChange: (change: { data: number }) => {
              if (applyingRemoteRef.current) {
                applyingRemoteRef.current = false;
                return;
              }
              if (!isControllerRef.current) {
                return;
              }
              const data = change.data;
              if (data === window.YT?.PlayerState?.ENDED) {
                sendRef.current({ type: "pause", payload: { time: 0 } });
                return;
              }
              if (data === window.YT?.PlayerState?.PAUSED) {
                sendRef.current({ type: "pause", payload: { time: playerRef.current?.getCurrentTime() } });
              } else if (data === window.YT?.PlayerState?.PLAYING) {
                sendRef.current({ type: "play", payload: { time: playerRef.current?.getCurrentTime() } });
              }
            },
          },
        });
        mountedVideoRef.current = videoId;

        window.setTimeout(() => {
          if (!readyRef.current && mountedVideoRef.current === videoId) {
            setStatus("error");
          }
        }, READY_TIMEOUT_MS);
      })
      .catch(() => {
        if (!cancelled) {
          setStatus("error");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [videoId, applyRemote]);

  // Apply server state (already seq-filtered by the reducer).
  useEffect(() => {
    if (lastStateRef.current === state) {
      return;
    }
    if (state.videoId && state.videoId !== mountedVideoRef.current) {
      // The embed is still building for the new video; record the state so the
      // new player's onReady applies it instead of the old video's state.
      lastStateRef.current = state;
      return;
    }
    applyRemote(state);
  }, [state, applyRemote]);

  // Drift correction (D-21), skipping buffering and projections.
  useEffect(() => {
    const timer = window.setInterval(() => {
      const player = playerRef.current;
      const last = lastStateRef.current;
      if (!readyRef.current || !player || last?.playState !== "playing") {
        return;
      }
      if (player.getPlayerState() === window.YT?.PlayerState?.BUFFERING) {
        return;
      }
      const expected = last.currentTime + (Date.now() - appliedAtRef.current) / 1000;
      const actual = player.getCurrentTime();
      if (Math.abs(actual - expected) > DRIFT_TOLERANCE) {
        player.seekTo(expected, true);
        appliedAtRef.current = Date.now();
        lastStateRef.current = { ...last, currentTime: expected };
      }
    }, DRIFT_CHECK_MS);
    return () => window.clearInterval(timer);
  }, []);

  return { containerRef, status };
}