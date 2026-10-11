import { useEffect } from "react";
import { useYouTubePlayer } from "../hooks/useYouTubePlayer";
import type { PlaybackState } from "../hooks/useRoomState";
import type { PlaybackAction } from "../hooks/useYouTubePlayer";

/**
 * YouTube embed (D-8): native controls hidden, overlay blocks clicks for
 * non-controllers. The click that opened this panel (Join & enable player)
 * is the autoplay gate (D-12). The hook owns the container div and creates
 * the <iframe> inside it via the IFrame API.
 */
export default function YouTubePlayer({
  videoId,
  state,
  isController,
  onAction,
}: {
  videoId: string | null;
  state: PlaybackState;
  isController: boolean;
  onAction: (action: PlaybackAction) => void;
}) {
  const { containerRef } = useYouTubePlayer({ videoId, state, onAction });

  useEffect(() => {
    console.log("[WP] youtube player mounted, videoId:", videoId ?? "(none)");
  }, [videoId]);

  return (
    <div className="youtube-player" data-testid="youtube-player">
      <div ref={containerRef} className="youtube-mount" />
      {!isController && <div className="player-overlay" aria-hidden />}
      {!videoId && <p className="player-empty">No video yet — the host can change it.</p>}
    </div>
  );
}
