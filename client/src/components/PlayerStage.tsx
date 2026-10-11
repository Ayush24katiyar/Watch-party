import { Clapperboard, Loader2, TriangleAlert } from "lucide-react";
import { useYouTubePlayer } from "../hooks/useYouTubePlayer";
import FloatingReactions from "./FloatingReactions";
import type { ClientEvent, Participant, PlaybackState } from "../lib/types";

/**
 * The embed (D-8): native controls hidden, a transparent overlay blocks clicks
 * for non-controllers. The click that opened the room is the autoplay gate (D-12).
 */
export default function PlayerStage({
  videoId,
  state,
  isController,
  reaction,
  participants,
  onAction,
}: {
  videoId: string | null;
  state: PlaybackState;
  isController: boolean;
  reaction: { userId: string; emoji: string } | null;
  participants: Participant[];
  onAction: (event: ClientEvent) => void;
}) {
  const { containerRef, status } = useYouTubePlayer({
    videoId,
    state,
    send: onAction,
    isController,
  });

  return (
    <div className="stage" data-testid="player-stage">
      <div className="stage-mount" ref={containerRef} />
      {!isController && videoId && <div className="stage-overlay" aria-hidden />}

      {!videoId && (
        <div className="stage-empty">
          <Clapperboard size={28} aria-hidden />
          <h2>Nothing queued yet</h2>
          <p>
            {isController
              ? "Paste a YouTube link below to start the screening."
              : "The host has not picked a video yet."}
          </p>
        </div>
      )}

      {videoId && status === "loading" && (
        <div className="stage-empty">
          <Loader2 size={24} aria-hidden />
          <p>Loading player...</p>
        </div>
      )}

      {videoId && status === "error" && (
        <div className="stage-empty">
          <TriangleAlert size={24} aria-hidden />
          <h2>Player unavailable</h2>
          <p>This video may block embedding, or YouTube is unreachable.</p>
        </div>
      )}

      <FloatingReactions current={reaction} participants={participants} />
    </div>
  );
}