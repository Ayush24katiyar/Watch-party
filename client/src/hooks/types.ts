/** Player control actions emitted by the ControlBar (architecture 8.2). */
export type PlaybackAction =
  | { type: "play"; payload: Record<string, unknown> }
  | { type: "pause"; payload: Record<string, unknown> }
  | { type: "seek"; payload: { time: number } }
  | { type: "change_video"; payload: { videoId: string } };
