/** YouTube URL parsing and the IFrame API loader (architecture 11, D-8). */

/**
 * Extract an 11-char video ID from a watch, share, shorts or embed URL, or
 * from a bare ID. Returns null for anything else so callers can show an
 * inline error rather than sending a value the server will reject.
 */
export function parseVideoId(input: string): string | null {
  const trimmed = input.trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(trimmed)) {
    return trimmed;
  }
  try {
    const url = new URL(trimmed);
    const host = url.hostname.replace(/^www\./, "");
    if (host === "youtu.be") {
      const id = url.pathname.slice(1).split("/")[0];
      return /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
    }
    if (host.endsWith("youtube.com")) {
      if (url.pathname === "/watch") {
        const id = url.searchParams.get("v");
        return id && /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
      }
      const match = url.pathname.match(/^\/(embed|shorts|live)\/([A-Za-z0-9_-]{11})/);
      return match ? match[2] : null;
    }
    return null;
  } catch {
    return null;
  }
}

type YtPlayerInstance = {
  playVideo: () => void;
  pauseVideo: () => void;
  seekTo: (seconds: number, allowSeekAhead: boolean) => void;
  getCurrentTime: () => number;
  getPlayerState: () => number;
  getDuration: () => number;
  isMuted: () => boolean;
  mute: () => void;
  unMute: () => void;
  destroy: () => void;
};

declare global {
  interface Window {
    YT?: {
      Player: new (element: HTMLElement, config: Record<string, unknown>) => YtPlayerInstance;
      PlayerState: {
        UNSTARTED: number;
        ENDED: number;
        PLAYING: number;
        PAUSED: number;
        BUFFERING: number;
        CUED: number;
      };
    };
    onYouTubeIframeAPIReady?: () => void;
  }
}

let apiPromise: Promise<void> | null = null;

/** Load the IFrame API once and resolve when `YT.Player` is usable. */
export function loadYouTubeApi(): Promise<void> {
  if (apiPromise) {
    return apiPromise;
  }
  apiPromise = new Promise((resolve, reject) => {
    if (window.YT?.Player) {
      resolve();
      return;
    }
    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      previous?.();
      resolve();
    };
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    script.async = true;
    script.onerror = () => {
      apiPromise = null;
      reject(new Error("The YouTube player could not be loaded."));
    };
    document.body.appendChild(script);
  });
  return apiPromise;
}